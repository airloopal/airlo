import os
from datetime import datetime, timedelta
from typing import Dict, Any

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# ✅ Your Stripe monthly link (upgrade from inside Telegram)
AIRLO_MONTHLY_LINK = "https://buy.stripe.com/3cI8wO3Hc0JC9zudZrgnK06"

# --- Simple per-user state store (MVP) ---
USER_STATE: Dict[int, Dict[str, Any]] = {}


# -------------------------
# Helpers: State + Access
# -------------------------
def get_state(user_id: int) -> Dict[str, Any]:
    if user_id not in USER_STATE:
        USER_STATE[user_id] = {"step": None, "data": {}, "prefs": {"airport": "Any", "priority": "Balanced"}}
    if "prefs" not in USER_STATE[user_id]:
        USER_STATE[user_id]["prefs"] = {"airport": "Any", "priority": "Balanced"}
    if "data" not in USER_STATE[user_id]:
        USER_STATE[user_id]["data"] = {}
    return USER_STATE[user_id]


def get_prefs(user_id: int) -> Dict[str, Any]:
    state = get_state(user_id)
    if "prefs" not in state:
        state["prefs"] = {"airport": "Any", "priority": "Balanced"}
    return state["prefs"]


def grant_access(user_id: int, tier: str, days: int):
    state = get_state(user_id)
    state["access_tier"] = tier
    state["access_until"] = datetime.utcnow() + timedelta(days=days)


def has_access(user_id: int) -> bool:
    state = get_state(user_id)
    until = state.get("access_until")
    if not until:
        return False
    return datetime.utcnow() < until


def access_status_text(user_id: int) -> str:
    state = get_state(user_id)
    tier = state.get("access_tier", "none")
    until = state.get("access_until")

    if not until:
        return "🔒 No access active.\n\nStart Airlo Monthly to continue using the bot."

    remaining = until - datetime.utcnow()
    hours = int(remaining.total_seconds() // 3600)
    if hours <= 0:
        return "🔒 Access expired.\n\nRestart Airlo Monthly to continue."

    # Basic, clear status (you can later add renewal date via Stripe webhook)
    return f"✅ Access: {tier}\n⏳ Expires in ~{hours} hours"


def reset_check(user_id: int):
    state = get_state(user_id)
    state["step"] = "CHECK_ENTRY"
    state["data"] = {}


def reset_when(user_id: int):
    state = get_state(user_id)
    state["step"] = "WHEN_ENTRY"
    state["data"] = {}


def kb(rows):
    return InlineKeyboardMarkup(rows)


async def send_upgrade_prompt(target):
    """
    Sends a clean upgrade prompt with Stripe Payment Link.
    target can be update.message or query.message (both support reply_text).
    """
    await target.reply_text(
        "🔒 Airlo access required\n\n"
        "Your trial has ended (or no access is active).\n"
        "Upgrade to continue using Trip Check + timing tools:",
        reply_markup=kb([
            [InlineKeyboardButton("Upgrade to Airlo (£19/month) 🔓", url=AIRLO_MONTHLY_LINK)]
        ])
    )


# -------------------------
# /when compute (rule-based)
# -------------------------
def timing_rules(when_data: Dict[str, Any]) -> Dict[str, Any]:
    route_type = when_data.get("route_type")        # SHORT, LONG, DOM, NS
    travel_window = when_data.get("travel_window")  # NM, 2_3, 4_6, PEAK, NS
    flex = when_data.get("flex")                    # VF, SF, FX
    pref_priority = (when_data.get("pref_priority") or "Balanced").lower()

    booking_window = "3–6 weeks before departure"
    why = [
        "Fares often stabilise in this window once airlines have clearer demand signals.",
        "Mid-week inventory typically prices cleaner than Fri–Sun peak demand.",
        "Booking too early can lock in inflated early-season pricing.",
    ]
    avoid = ["Booking on weekends", "Locking in too early without fixed dates"]
    tip = "If you can, aim for Tue–Wed departures and compare nearby airports."

    # Route type tweaks
    if route_type == "LONG":
        booking_window = "6–10 weeks before departure"
        why[0] = "Long-haul fares often reward earlier planning due to limited cabin inventory."
    elif route_type == "DOM":
        booking_window = "2–4 weeks before departure"
        why[0] = "Domestic routes can price best closer in, unless it’s a peak travel week."

    # Travel window tweaks
    if travel_window == "PEAK":
        booking_window = "8–12 weeks before departure"
        why[1] = "Peak season load factors climb early, pushing prices up sooner."
        avoid = ["Last-minute booking", "Fri–Sun peak travel days"]
    elif travel_window == "NM":
        avoid = ["Waiting too long if dates are fixed", "Fri–Sun departures"]

    # Flex tweaks
    if flex == "FX":
        tip = "With fixed dates, book within the recommended window to reduce pricing risk."
    elif flex == "VF":
        tip = "With high flexibility, wait for dips and avoid peak days to improve value."

    # Preference-based tip tweaks
    if pref_priority == "cheapest":
        tip = "Cheapest-first: avoid Fri–Sun, target Tue–Wed, and compare alternate airports."
    elif pref_priority == "fastest":
        tip = "Fastest-first: book earlier in the window to secure direct routings and short connections."
    elif pref_priority == "comfort":
        tip = "Comfort-first: book earlier to secure better departure times, seat options, and fewer connections."

    return {
        "booking_window": booking_window,
        "why": why[:3],
        "avoid": avoid[:2],
        "tip": tip,
    }


# -------------------------
# /check compute (rule-based)
# -------------------------
def rule_based_verdict(data: Dict[str, Any]) -> Dict[str, Any]:
    window = data.get("window")  # 0_2, 2_6, 1_3, 3P, NS
    priority_raw = (data.get("priority") or "BAL").upper()  # CHEAP/BAL/FAST/COMF
    pref_priority = (data.get("pref_priority") or "Balanced").lower()
    pref_airport = data.get("pref_airport") or "Any"

    verdict = "WAIT"
    reasons = []
    options = []

    if window == "0_2":
        verdict = "BOOK" if priority_raw in ("FAST", "COMF") else "WAIT"
        reasons.append("Close to departure: fares can swing quickly as inventory tightens.")
        reasons.append("Peak-day demand (Fri/Sun) can add a premium even on short routes.")
        options.append("If possible, shift to Tue–Wed or Saturday for cleaner pricing.")
    elif window == "2_6":
        verdict = "BOOK"
        reasons.append("This is commonly the best optimisation window for many short/medium routes.")
        reasons.append("Airlines have set pricing bands but demand hasn’t fully peaked yet.")
        options.append("Compare airport pairs (e.g., LHR vs LGW) for better value.")
    elif window == "1_3":
        verdict = "WAIT"
        reasons.append("Often early for best pricing — good for planning, not always for buying.")
        reasons.append("Watch for dips around 3–6 weeks pre-departure on many routes.")
        options.append("If it’s peak season or fixed dates, consider booking earlier.")
    elif window == "3P":
        verdict = "WAIT"
        reasons.append("Usually too early to lock the best price unless it’s peak dates.")
        reasons.append("Better value often appears closer to the optimal window.")
        options.append("Set a reminder and re-check as you approach 8–12 / 3–6 weeks.")
    else:
        verdict = "WAIT"
        reasons.append("Without dates, safest move is to benchmark typical booking windows.")
        options.append("Run /when for a route-based booking window.")

    # Preference-aware tweaks
    if pref_priority == "cheapest":
        options.insert(0, "Cheapest-first: aim Tue–Wed and avoid Fri–Sun if possible.")
        options.insert(1, f"Default airport setting: {pref_airport} (adjust in Preferences).")
        reasons.append("Cheapest-first trips benefit most from flexibility and airport pair comparisons.")
    elif pref_priority == "fastest":
        options.insert(0, "Fastest-first: prioritise direct routings and minimal connections.")
        options.insert(1, "Book earlier in the window to secure the best direct inventory.")
        reasons.append("Fastest-first trips often need earlier booking to lock direct seats.")
    elif pref_priority == "comfort":
        options.insert(0, "Comfort-first: avoid extreme departure times and multiple connections.")
        options.insert(1, "Book earlier to secure better cabin/seat availability.")
        reasons.append("Comfort-first trips benefit from better timing and route quality.")

    return {"verdict": verdict, "reasons": reasons[:3], "options": options[:3]}


async def send_result(obj, data: Dict[str, Any], is_message: bool = False):
    user_id = obj.from_user.id if hasattr(obj, "from_user") else None
    prefs = get_prefs(user_id) if user_id else {"airport": "Any", "priority": "Balanced"}

    data["pref_priority"] = prefs.get("priority", "Balanced")
    data["pref_airport"] = prefs.get("airport", "Any")

    if data.get("departure") in (None, "", "ANY", "Any", "ANY LONDON", "LON"):
        if prefs.get("airport") not in ("Any", "ANY"):
            data["departure"] = prefs["airport"]

    from_ = data.get("departure", "—")
    to_ = data.get("destination", "—")
    trip_type = data.get("trip_type", "—")
    priority = data.get("priority", "BAL")
    price = data.get("price")

    verdict_pack = rule_based_verdict(data)

    text = (
        "✈️ Airlo Trip Check\n\n"
        "Route\n"
        f"{from_} → {to_}\n"
        f"{trip_type} · {str(priority).title()} priority\n"
        f"{('Price: ' + str(price)) if price else ''}\n\n"
        "Verdict\n"
        f"{verdict_pack['verdict']}\n\n"
        "Why this matters\n"
        f"• {verdict_pack['reasons'][0]}\n"
        f"• {verdict_pack['reasons'][1]}\n"
        f"{('• ' + verdict_pack['reasons'][2]) if len(verdict_pack['reasons']) > 2 else ''}\n\n"
        "Smarter options\n"
        f"• {verdict_pack['options'][0]}\n"
        f"{('• ' + verdict_pack['options'][1]) if len(verdict_pack['options']) > 1 else ''}\n"
        f"{('• ' + verdict_pack['options'][2]) if len(verdict_pack['options']) > 2 else ''}\n\n"
        "Best next step\n"
        "Re-check closer to the optimal booking window."
    ).strip()

    buttons = kb([
        [InlineKeyboardButton("Run another check 🔁", callback_data="CHECK_START")],
        [InlineKeyboardButton("Preferences ⚙️", callback_data="SETTINGS_BACK")],
        [InlineKeyboardButton("Best time to book ⏱", callback_data="WHEN_START")],
    ])

    if is_message:
        await obj.reply_text(text, reply_markup=buttons)
    else:
        await obj.edit_message_text(text, reply_markup=buttons)


# -------------------------
# Commands
# -------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    # Deep-link unlock codes (V1)
    # Website success page can send users to: t.me/AirloBot?start=trial7
    if context.args:
        code = context.args[0].lower()
        if code == "trial7":
            grant_access(user_id, "trial", 7)
        elif code == "premium":
            grant_access(user_id, "premium", 30)  # placeholder until webhook verification

    await update.message.reply_text(
        "✈️ Welcome to Airlo\n\n"
        "We help you avoid peak-day markups, bad routings, and booking at the wrong time.\n\n"
        "Pick what you need:",
        reply_markup=kb([
            [InlineKeyboardButton("✅ Trip Check", callback_data="CHECK_START")],
            [InlineKeyboardButton("⏱ Best Time to Book", callback_data="WHEN_START")],
            [InlineKeyboardButton("⚙️ Preferences", callback_data="SETTINGS_BACK")],
            [InlineKeyboardButton("📌 Status", callback_data="SHOW_STATUS")],
        ])
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "Available commands:\n\n"
        "/check — Trip sanity check (timing / route / options)\n"
        "/when — Best booking window (rule-based)\n"
        "/settings — Set default airport + priority\n"
        "/status — Access status + upgrade\n"
        "/help — This menu"
    )
    await update.message.reply_text(text)


async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = access_status_text(user_id)

    if not has_access(user_id):
        await update.message.reply_text(
            text,
            reply_markup=kb([
                [InlineKeyboardButton("Upgrade to Airlo (£19/month) 🔓", url=AIRLO_MONTHLY_LINK)]
            ])
        )
    else:
        await update.message.reply_text(text)


async def check_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not has_access(user_id):
        await send_upgrade_prompt(update.message)
        return

    reset_check(user_id)
    await update.message.reply_text(
        "✅ Trip Check\n\n"
        "Quick questions — then you’ll get a fare/timing sanity check.",
        reply_markup=kb([
            [InlineKeyboardButton("Start Trip Check ✅", callback_data="CHECK_START")],
            [InlineKeyboardButton("What this does ℹ️", callback_data="CHECK_INFO")],
        ])
    )


async def when_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not has_access(user_id):
        await send_upgrade_prompt(update.message)
        return

    reset_when(user_id)
    await update.message.reply_text(
        "⏱ Best Time to Book\n\n"
        "Answer a few questions and Airlo will suggest the optimal booking window.",
        reply_markup=kb([
            [InlineKeyboardButton("Start ⏱", callback_data="WHEN_START")],
            [InlineKeyboardButton("What this does ℹ️", callback_data="WHEN_INFO")],
        ])
    )


async def settings_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    prefs = get_prefs(user_id)

    text = (
        "⚙️ Preferences\n\n"
        f"Departure airport: {prefs['airport']}\n"
        f"Travel priority: {prefs['priority']}\n\n"
        "Update your preferences below."
    )

    await update.message.reply_text(
        text,
        reply_markup=kb([
            [InlineKeyboardButton("Departure airport ✈️", callback_data="SET_AIRPORT")],
            [InlineKeyboardButton("Travel priority 🎯", callback_data="SET_PRIORITY")],
            [InlineKeyboardButton("Reset preferences ♻️", callback_data="SET_RESET")],
        ])
    )


# -------------------------
# Buttons (Callback router)
# -------------------------
async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    state = get_state(user_id)
    data = state["data"]
    cd = query.data

    print("BUTTON CLICKED:", cd)

    # Quick status
    if cd == "SHOW_STATUS":
        text = access_status_text(user_id)
        if not has_access(user_id):
            await query.edit_message_text(text)
            await send_upgrade_prompt(query.message)
        else:
            await query.edit_message_text(text, reply_markup=kb([[InlineKeyboardButton("Back ◀️", callback_data="START_MENU")]]))
        return

    if cd == "START_MENU":
        await query.edit_message_text(
            "✈️ Welcome to Airlo\n\nPick what you need:",
            reply_markup=kb([
                [InlineKeyboardButton("✅ Trip Check", callback_data="CHECK_START")],
                [InlineKeyboardButton("⏱ Best Time to Book", callback_data="WHEN_START")],
                [InlineKeyboardButton("⚙️ Preferences", callback_data="SETTINGS_BACK")],
                [InlineKeyboardButton("📌 Status", callback_data="SHOW_STATUS")],
            ])
        )
        return

    # -------------------------
    # Settings
    # -------------------------
    if cd == "SET_AIRPORT":
        await query.edit_message_text(
            "Select your default departure airport:",
            reply_markup=kb([
                [InlineKeyboardButton("Any London", callback_data="SET_AP_LON")],
                [InlineKeyboardButton("LHR", callback_data="SET_AP_LHR"),
                 InlineKeyboardButton("LGW", callback_data="SET_AP_LGW")],
                [InlineKeyboardButton("MAN", callback_data="SET_AP_MAN")],
                [InlineKeyboardButton("Any", callback_data="SET_AP_ANY")],
                [InlineKeyboardButton("Back ◀️", callback_data="SETTINGS_BACK")],
            ])
        )
        return

    if cd.startswith("SET_AP_"):
        prefs = get_prefs(user_id)
        prefs["airport"] = cd.replace("SET_AP_", "")
        await query.edit_message_text(
            f"✅ Departure airport set to {prefs['airport']}",
            reply_markup=kb([[InlineKeyboardButton("Back to settings ⚙️", callback_data="SETTINGS_BACK")]])
        )
        return

    if cd == "SET_PRIORITY":
        await query.edit_message_text(
            "Select your default travel priority:",
            reply_markup=kb([
                [InlineKeyboardButton("Cheapest", callback_data="SET_PR_CHEAP")],
                [InlineKeyboardButton("Balanced", callback_data="SET_PR_BAL")],
                [InlineKeyboardButton("Fastest", callback_data="SET_PR_FAST")],
                [InlineKeyboardButton("Comfort", callback_data="SET_PR_COMF")],
                [InlineKeyboardButton("Back ◀️", callback_data="SETTINGS_BACK")],
            ])
        )
        return

    if cd.startswith("SET_PR_"):
        prefs = get_prefs(user_id)
        prefs["priority"] = cd.replace("SET_PR_", "").title()
        await query.edit_message_text(
            f"✅ Travel priority set to {prefs['priority']}",
            reply_markup=kb([[InlineKeyboardButton("Back to settings ⚙️", callback_data="SETTINGS_BACK")]])
        )
        return

    if cd == "SET_RESET":
        state = get_state(user_id)
        state["prefs"] = {"airport": "Any", "priority": "Balanced"}
        await query.edit_message_text(
            "♻️ Preferences reset to default.",
            reply_markup=kb([[InlineKeyboardButton("Back to settings ⚙️", callback_data="SETTINGS_BACK")]])
        )
        return

    if cd == "SETTINGS_BACK":
        prefs = get_prefs(user_id)
        await query.edit_message_text(
            "⚙️ Preferences\n\n"
            f"Departure airport: {prefs['airport']}\n"
            f"Travel priority: {prefs['priority']}\n\n"
            "Update your preferences below.",
            reply_markup=kb([
                [InlineKeyboardButton("Departure airport ✈️", callback_data="SET_AIRPORT")],
                [InlineKeyboardButton("Travel priority 🎯", callback_data="SET_PRIORITY")],
                [InlineKeyboardButton("Reset preferences ♻️", callback_data="SET_RESET")],
                [InlineKeyboardButton("Back ◀️", callback_data="START_MENU")],
            ])
        )
        return

    # -------------------------
    # /when flow
    # -------------------------
    if cd == "WHEN_INFO":
        await query.edit_message_text(
            "Airlo suggests the best booking window based on route type, seasonality, and flexibility.",
            reply_markup=kb([[InlineKeyboardButton("Start ⏱", callback_data="WHEN_START")]])
        )
        return

    if cd == "WHEN_START":
        if not has_access(user_id):
            await query.edit_message_text("🔒 Airlo access required.")
            await send_upgrade_prompt(query.message)
            return

        reset_when(user_id)
        state["step"] = "WHEN_ROUTE_TYPE"
        await query.edit_message_text(
            "What kind of route is this?",
            reply_markup=kb([
                [InlineKeyboardButton("Short-haul (Europe)", callback_data="WHEN_RT_SHORT")],
                [InlineKeyboardButton("Long-haul", callback_data="WHEN_RT_LONG")],
                [InlineKeyboardButton("Domestic", callback_data="WHEN_RT_DOM")],
                [InlineKeyboardButton("Not sure", callback_data="WHEN_RT_NS")],
            ])
        )
        return

    if cd.startswith("WHEN_RT_"):
        data["route_type"] = cd.replace("WHEN_RT_", "")
        state["step"] = "WHEN_TRAVEL_WINDOW"
        await query.edit_message_text(
            "When are you travelling?",
            reply_markup=kb([
                [InlineKeyboardButton("Next month", callback_data="WHEN_TW_NM")],
                [InlineKeyboardButton("2–3 months", callback_data="WHEN_TW_2_3")],
                [InlineKeyboardButton("4–6 months", callback_data="WHEN_TW_4_6")],
                [InlineKeyboardButton("Peak season", callback_data="WHEN_TW_PEAK")],
                [InlineKeyboardButton("Not sure", callback_data="WHEN_TW_NS")],
            ])
        )
        return

    if cd.startswith("WHEN_TW_"):
        data["travel_window"] = cd.replace("WHEN_TW_", "")
        state["step"] = "WHEN_FLEX"
        await query.edit_message_text(
            "How flexible are you?",
            reply_markup=kb([
                [InlineKeyboardButton("Very flexible", callback_data="WHEN_FX_VF")],
                [InlineKeyboardButton("Somewhat flexible", callback_data="WHEN_FX_SF")],
                [InlineKeyboardButton("Fixed dates", callback_data="WHEN_FX_FX")],
            ])
        )
        return

    if cd.startswith("WHEN_FX_"):
        data["flex"] = cd.replace("WHEN_FX_", "")
        state["step"] = "WHEN_DONE"

        prefs = get_prefs(user_id)
        data["pref_priority"] = prefs.get("priority", "Balanced")

        insight = timing_rules(data)

        text = (
            "⏱ Airlo Timing Insight\n\n"
            "Recommended booking window\n"
            f"{insight['booking_window']}\n\n"
            "Why\n"
            f"• {insight['why'][0]}\n"
            f"• {insight['why'][1]}\n"
            f"• {insight['why'][2]}\n\n"
            "Avoid\n"
            f"• {insight['avoid'][0]}\n"
            f"• {insight['avoid'][1]}\n\n"
            "Tip\n"
            f"{insight['tip']}"
        )

        await query.edit_message_text(
            text,
            reply_markup=kb([
                [InlineKeyboardButton("Run a Trip Check ✈️", callback_data="CHECK_START")],
                [InlineKeyboardButton("Back ◀️", callback_data="START_MENU")],
            ])
        )
        return

    # -------------------------
    # /check flow
    # -------------------------
    if cd == "CHECK_INFO":
        await query.edit_message_text(
            "Airlo reviews your route, timing, and options to help you avoid overpriced or inefficient bookings.",
            reply_markup=kb([[InlineKeyboardButton("Start Trip Check ✅", callback_data="CHECK_START")]])
        )
        return

    if cd == "CHECK_START":
        if not has_access(user_id):
            await query.edit_message_text("🔒 Airlo access required.")
            await send_upgrade_prompt(query.message)
            return

        reset_check(user_id)
        state["step"] = "TRIP_TYPE"
        await query.edit_message_text(
            "What type of trip is this?",
            reply_markup=kb([
                [InlineKeyboardButton("Return 🔁", callback_data="TRIP_RETURN")],
                [InlineKeyboardButton("One-way ➡️", callback_data="TRIP_ONEWAY")],
            ])
        )
        return

    if cd in ("TRIP_RETURN", "TRIP_ONEWAY"):
        data["trip_type"] = "Return" if cd == "TRIP_RETURN" else "One-way"
        state["step"] = "DEP_REGION"
        await query.edit_message_text(
            "Where are you departing from?",
            reply_markup=kb([
                [InlineKeyboardButton("UK & Ireland 🇬🇧", callback_data="DEP_UK")],
                [InlineKeyboardButton("Europe 🇪🇺", callback_data="DEP_EU")],
                [InlineKeyboardButton("USA 🇺🇸", callback_data="DEP_US")],
                [InlineKeyboardButton("Other 🌍", callback_data="DEP_OTHER")],
            ])
        )
        return

    if cd.startswith("DEP_"):
        data["dep_region"] = cd.replace("DEP_", "")
        state["step"] = "DEP_AREA"
        if cd == "DEP_UK":
            await query.edit_message_text(
                "Select your departure area:",
                reply_markup=kb([
                    [InlineKeyboardButton("London", callback_data="DEPAREA_LONDON")],
                    [InlineKeyboardButton("Manchester", callback_data="DEPAREA_MAN")],
                    [InlineKeyboardButton("Birmingham", callback_data="DEPAREA_BHX")],
                    [InlineKeyboardButton("Other (type it)", callback_data="DEPAREA_TYPE")],
                ])
            )
        else:
            state["step"] = "DEP_TYPED"
            await query.edit_message_text("Type your departure city/airport (e.g., Paris CDG):")
        return

    if cd == "DEPAREA_LONDON":
        state["step"] = "DEP_LONDON_AIRPORT"
        await query.edit_message_text(
            "Which London airport?",
            reply_markup=kb([
                [InlineKeyboardButton("LHR", callback_data="DEPAPT_LHR"), InlineKeyboardButton("LGW", callback_data="DEPAPT_LGW")],
                [InlineKeyboardButton("STN", callback_data="DEPAPT_STN"), InlineKeyboardButton("LTN", callback_data="DEPAPT_LTN")],
                [InlineKeyboardButton("LCY", callback_data="DEPAPT_LCY"), InlineKeyboardButton("Any London", callback_data="DEPAPT_ANY")],
            ])
        )
        return

    if cd.startswith("DEPAPT_"):
        val = cd.replace("DEPAPT_", "")
        data["departure"] = "ANY LONDON" if val == "ANY" else val
        state["step"] = "DEST_REGION"
        await query.edit_message_text(
            "Where are you travelling to?",
            reply_markup=kb([
                [InlineKeyboardButton("Europe 🇪🇺", callback_data="DST_EU")],
                [InlineKeyboardButton("USA 🇺🇸", callback_data="DST_US")],
                [InlineKeyboardButton("Middle East 🌍", callback_data="DST_ME")],
                [InlineKeyboardButton("Asia 🌏", callback_data="DST_AS")],
                [InlineKeyboardButton("Other 🌍", callback_data="DST_OTHER")],
                [InlineKeyboardButton("Type a city", callback_data="DST_TYPE")],
            ])
        )
        return

    if cd.startswith("DST_"):
        state["step"] = "DEST_PICK"
        if cd == "DST_EU":
            await query.edit_message_text(
                "Choose a destination (or type):",
                reply_markup=kb([
                    [InlineKeyboardButton("Paris", callback_data="DEST_Paris"), InlineKeyboardButton("Rome", callback_data="DEST_Rome")],
                    [InlineKeyboardButton("Barcelona", callback_data="DEST_Barcelona"), InlineKeyboardButton("Amsterdam", callback_data="DEST_Amsterdam")],
                    [InlineKeyboardButton("Type a city", callback_data="DEST_TYPE")],
                ])
            )
        else:
            state["step"] = "DEST_TYPED"
            await query.edit_message_text("Type your destination city/airport:")
        return

    if cd == "DEST_TYPE":
        state["step"] = "DEST_TYPED"
        await query.edit_message_text("Type your destination city/airport:")
        return

    if cd.startswith("DEST_") and cd != "DEST_TYPE":
        data["destination"] = cd.replace("DEST_", "")
        state["step"] = "TRAVEL_WINDOW"
        await query.edit_message_text(
            "When are you travelling?",
            reply_markup=kb([
                [InlineKeyboardButton("Next 2 weeks", callback_data="WIN_0_2")],
                [InlineKeyboardButton("2–6 weeks", callback_data="WIN_2_6")],
                [InlineKeyboardButton("1–3 months", callback_data="WIN_1_3")],
                [InlineKeyboardButton("3+ months", callback_data="WIN_3P")],
                [InlineKeyboardButton("Not sure", callback_data="WIN_NS")],
            ])
        )
        return

    if cd.startswith("WIN_"):
        data["window"] = cd.replace("WIN_", "")
        state["step"] = "PRIORITY"
        await query.edit_message_text(
            "What matters most?",
            reply_markup=kb([
                [InlineKeyboardButton("Cheapest", callback_data="PR_CHEAP")],
                [InlineKeyboardButton("Balanced", callback_data="PR_BAL")],
                [InlineKeyboardButton("Fastest", callback_data="PR_FAST")],
                [InlineKeyboardButton("Comfort", callback_data="PR_COMF")],
            ])
        )
        return

    if cd.startswith("PR_"):
        pr = cd.replace("PR_", "")
        data["priority"] = pr
        state["step"] = "ASK_PRICE"
        await query.edit_message_text(
            "Do you have a price you’re considering?",
            reply_markup=kb([
                [InlineKeyboardButton("Yes (type £ amount)", callback_data="PRICE_YES")],
                [InlineKeyboardButton("No", callback_data="PRICE_NO")],
            ])
        )
        return

    if cd == "PRICE_NO":
        data["price"] = None
        state["step"] = "DONE"
        await send_result(query, data)
        return

    if cd == "PRICE_YES":
        state["step"] = "PRICE_TYPED"
        await query.edit_message_text("Type the total price (e.g. £340):")
        return

    # Fallback
    await query.edit_message_text(
        "Use /start to begin.",
        reply_markup=kb([[InlineKeyboardButton("Start ◀️", callback_data="START_MENU")]])
    )


# -------------------------
# Text handler
# -------------------------
async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    state = get_state(user_id)
    step = state["step"]
    data = state["data"]
    msg = update.message.text.strip()

    if step == "DEP_TYPED":
        data["departure"] = msg
        state["step"] = "DEST_REGION"
        await update.message.reply_text(
            "Where are you travelling to?",
            reply_markup=kb([
                [InlineKeyboardButton("Europe 🇪🇺", callback_data="DST_EU")],
                [InlineKeyboardButton("USA 🇺🇸", callback_data="DST_US")],
                [InlineKeyboardButton("Middle East 🌍", callback_data="DST_ME")],
                [InlineKeyboardButton("Asia 🌏", callback_data="DST_AS")],
                [InlineKeyboardButton("Other 🌍", callback_data="DST_OTHER")],
                [InlineKeyboardButton("Type a city", callback_data="DST_TYPE")],
            ])
        )
        return

    if step == "DEST_TYPED":
        data["destination"] = msg
        state["step"] = "TRAVEL_WINDOW"
        await update.message.reply_text(
            "When are you travelling?",
            reply_markup=kb([
                [InlineKeyboardButton("Next 2 weeks", callback_data="WIN_0_2")],
                [InlineKeyboardButton("2–6 weeks", callback_data="WIN_2_6")],
                [InlineKeyboardButton("1–3 months", callback_data="WIN_1_3")],
                [InlineKeyboardButton("3+ months", callback_data="WIN_3P")],
                [InlineKeyboardButton("Not sure", callback_data="WIN_NS")],
            ])
        )
        return

    if step == "PRICE_TYPED":
        data["price"] = msg
        state["step"] = "DONE"
        await update.message.reply_text("Thanks — generating your Airlo Trip Check ✅")
        await send_result(update.message, data, is_message=True)
        return

    await update.message.reply_text("Use /start to begin. Or /help for commands.")


# -------------------------
# Bootstrap
# -------------------------
def main():
    if not TOKEN:
        raise RuntimeError("Missing TELEGRAM_BOT_TOKEN env var.")

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("check", check_cmd))
    app.add_handler(CommandHandler("when", when_cmd))
    app.add_handler(CommandHandler("settings", settings_cmd))

    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    app.run_polling()


if __name__ == "__main__":
    main()
