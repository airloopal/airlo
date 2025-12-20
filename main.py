import os
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
from datetime import datetime, timedelta


TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# --- Simple per-user state store (MVP) ---
# In production you'd use a database, but for V1 this is enough.
USER_STATE: Dict[int, Dict[str, Any]] = {}

# --- Helpers ---
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
        return "🔒 No access active.\n\nGet 7-day access for £1 at tryairlo.com"
    remaining = until - datetime.utcnow()
    hours = int(remaining.total_seconds() // 3600)
    if hours < 0:
        return "🔒 Access expired.\n\nRenew at tryairlo.com"
    return f"✅ Access: {tier}\n⏳ Expires in ~{hours} hours"

def get_state(user_id: int) -> Dict[str, Any]:
    if user_id not in USER_STATE:
        USER_STATE[user_id] = {"step": None, "data": {}}
    return USER_STATE[user_id]

def reset_check(user_id: int):
    USER_STATE[user_id] = {"step": "CHECK_ENTRY", "data": {}}

def reset_when(user_id: int):
    USER_STATE[user_id] = {"step": "WHEN_ENTRY", "data": {}}

def get_prefs(user_id: int) -> Dict[str, Any]:
    state = get_state(user_id)
    if "prefs" not in state:
        state["prefs"] = {
            "airport": "Any",
            "priority": "Balanced"
        }
    return state["prefs"]

def timing_rules(when_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Free, rule-based timing output. No APIs, no AI.
    """
    route_type = when_data.get("route_type")   # SHORT, LONG, DOM, NS
    travel_window = when_data.get("travel_window")  # NM, 2_3, 4_6, PEAK, NS
    flex = when_data.get("flex")  # VF, SF, FX
    pref_priority = when_data.get("pref_priority", "Balanced")


    # Defaults
    booking_window = "3–6 weeks before departure"
    why = [
        "Prices often stabilise in this window for many routes.",
        "Mid-week travel tends to reduce demand pressure.",
        "Booking too early can lock in inflated pricing.",
    ]
    avoid = ["Booking on weekends", "Booking too far in advance without a reason"]
    tip = "If flexible, aim for Tue–Wed travel for better value."

    tip = "Default timing advice here"

    # Preference-based tip tweaks
    if pref_priority.lower() == "cheapest":
        tip = "For lowest fares, avoid Fri–Sun travel and book mid-week where possible."
    elif pref_priority.lower() == "fastest":
        tip = "For fastest itineraries, book earlier in the window to secure direct routes."
    elif pref_priority.lower() == "comfort":
        tip = "For comfort, book earlier in the window to secure better flight times and seating options."

    return {
        "booking_window": booking_window,
        "why": why[:3],
        "avoid": avoid[:2],
        "tip": tip
    }

    # Route type tweaks
    if route_type == "LONG":
        booking_window = "6–10 weeks before departure"
        why[0] = "Long-haul pricing often rewards earlier planning."
    if route_type == "DOM":
        booking_window = "2–4 weeks before departure"
        why[0] = "Short domestic routes can price best closer in."
    if route_type == "NS":
        booking_window = "3–6 weeks before departure"

    # Travel window tweaks
    if travel_window == "PEAK":
        booking_window = "8–12 weeks before departure"
        why[1] = "Peak season demand pushes fares up earlier."
        avoid = ["Last-minute booking", "Fri–Sun peak travel days"]
    elif travel_window == "4_6":
        why[2] = "You can often wait before committing unless it’s peak season."
    elif travel_window == "NM":
        avoid = ["Waiting too long if dates are fixed", "Fri–Sun departures"]

    # Flex tweaks
    if flex == "FX":
        tip = "With fixed dates, book within the recommended window to reduce risk."
    elif flex == "VF":
        tip = "With high flexibility, you can wait for dips and avoid peak travel days."

    return {
        "booking_window": booking_window,
        "why": why[:3],
        "avoid": avoid[:2],
        "tip": tip
    }

def kb(rows):
    return InlineKeyboardMarkup(rows)

# --- Command: /start ---
async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await update.message.reply_text(access_status_text(user_id))

    # Deep-link unlock codes (V1)
    # Website success page will send users to: t.me/AirloBot?start=trial7
    if context.args:
        code = context.args[0].lower()
        if code == "trial7":
            grant_access(user_id, "trial", 7)
        elif code == "premium":
            grant_access(user_id, "premium", 30)  # placeholder until Stripe webhook

    # ... keep your existing welcome/menu reply below

    await update.message.reply_text(
        "✈️ Welcome to *Airlo*\n\n"
        "Pick what you need:",
        parse_mode="Markdown",
        reply_markup=kb([
            [InlineKeyboardButton("✅ Trip Check", callback_data="CHECK_START")],
            [InlineKeyboardButton("⏱ Best Time to Book", callback_data="WHEN_START")],
            [InlineKeyboardButton("⚙️ Preferences", callback_data="SETTINGS_BACK")],
        ])
    )

# --- Command: /help ---

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        await update.message.reply_text(access_status_text(user_id))

    user_id = update.effective_user.id
    await update.message.reply_text(access_status_text(user_id))
    text = (
        "Available commands:\n\n"
        "/check — Sense-check a trip before booking\n"
        "/when — Best time to book (coming next)\n"
        "/settings — Preferences (coming next)\n"
        "/help — This menu"
    )
    await update.message.reply_text(text)

# --- Command: /check (Entry screen) ---
async def when_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await update.message.reply_text(access_status_text(user_id))
    user_id = update.effective_user.id
    reset_when(user_id)

    await update.message.reply_text(
        "⏱ *Best Time to Book*\nAnswer a few quick questions and Airlo will suggest the optimal booking window.",
        parse_mode="Markdown",
        reply_markup=kb([
            [InlineKeyboardButton("Start ⏱", callback_data="WHEN_START")],
            [InlineKeyboardButton("What this does ℹ️", callback_data="WHEN_INFO")],
        ])
    )


async def settings_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await update.message.reply_text(access_status_text(user_id))
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


    user_id = update.effective_user.id
    reset_when(user_id)

    await update.message.reply_text(
        "⏱ *Best Time to Book*\nAnswer a few quick questions and Airlo will suggest the optimal booking window.",
        parse_mode="Markdown",
        reply_markup=kb([
            [InlineKeyboardButton("Start ⏱", callback_data="WHEN_START")],
            [InlineKeyboardButton("What this does ℹ️", callback_data="WHEN_INFO")],
        ])
    )
    
    user_id = update.effective_user.id
    reset_check(user_id)

    await update.message.reply_text(
        "✅ *Trip Check*\nAnswer a few quick questions and Airlo will sense-check your trip.",
        parse_mode="Markdown",
        reply_markup=kb([
            [InlineKeyboardButton("Start Trip Check ✅", callback_data="CHECK_START")],
            [InlineKeyboardButton("What this does ℹ️", callback_data="CHECK_INFO")],
        ])
    )

# --- Callback router ---
async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    state = get_state(user_id)
    data = state["data"]

    cd = query.data
    print("BUTTON CLICKED:", cd)

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
            f"Travel priority: {prefs['priority']}",
            reply_markup=kb([
                [InlineKeyboardButton("Departure airport ✈️", callback_data="SET_AIRPORT")],
                [InlineKeyboardButton("Travel priority 🎯", callback_data="SET_PRIORITY")],
                [InlineKeyboardButton("Reset preferences ♻️", callback_data="SET_RESET")],
            ])
        )
        return

    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    state = get_state(user_id)
    data = state["data"]

    cd = query.data

    # -------------------------
    # /settings flow
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
            ])
        )
        return


    # -------------------------
    # /when flow (buttons)
    # -------------------------
    if cd == "WHEN_INFO":
        await query.edit_message_text(
            "Airlo gives you the best booking window based on route type, seasonality, and flexibility.\n\n"
            "Tap *Start* to continue.",
            parse_mode="Markdown",
            reply_markup=kb([[InlineKeyboardButton("Start ⏱", callback_data="WHEN_START")]])
        )
        return

    if cd == "WHEN_START":
        if not has_access(user_id):
            await query.edit_message_text(
                "🔒 Airlo access required\n\nGet 7-day access for £1 at tryairlo.com\nThen £19/month."
            )
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
        rt = cd.replace("WHEN_RT_", "")  # SHORT/LONG/DOM/NS
        data["route_type"] = rt
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
        tw = cd.replace("WHEN_TW_", "")  # NM/2_3/4_6/PEAK/NS
        data["travel_window"] = tw
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
        fx = cd.replace("WHEN_FX_", "")  # VF/SF/FX
        data["flex"] = fx
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
                [InlineKeyboardButton("Preferences ⚙️", callback_data="SETTINGS_SOON")],
            ])
        )
        return
    
    # Info
    if cd == "CHECK_INFO":
        await query.edit_message_text(
            "Airlo reviews your route, timing, and options to help you avoid overpriced or inefficient bookings.\n\n"
            "Tap *Start Trip Check* to begin.",
            parse_mode="Markdown",
            reply_markup=kb([[InlineKeyboardButton("Start Trip Check ✅", callback_data="CHECK_START")]])
        )
        return

    # Start -> Trip type
    if cd == "CHECK_START":
        if not has_access(user_id):
            await query.edit_message_text(
                "🔒 Airlo access required\n\nGet 7-day access for £1 at tryairlo.com\nThen £19/month."
            )
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


    # Trip type chosen -> Departure region
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

    # Departure region -> prompt for airport area
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
            await query.edit_message_text(
                "Type your departure city/airport (e.g., Paris CDG):"
            )
            state["step"] = "DEP_TYPED"
        return

    # London airports
    if cd == "DEPAREA_LONDON":
        state["step"] = "DEP_LONDON_AIRPORT"
        await query.edit_message_text(
            "Which London airport?",
            reply_markup=kb([
                [InlineKeyboardButton("LHR", callback_data="DEPAPT_LHR"),
                 InlineKeyboardButton("LGW", callback_data="DEPAPT_LGW")],
                [InlineKeyboardButton("STN", callback_data="DEPAPT_STN"),
                 InlineKeyboardButton("LTN", callback_data="DEPAPT_LTN")],
                [InlineKeyboardButton("LCY", callback_data="DEPAPT_LCY"),
                 InlineKeyboardButton("Any London", callback_data="DEPAPT_ANY")],
            ])
        )
        return

    if cd.startswith("DEPAPT_"):
        data["departure"] = cd.replace("DEPAPT_", "")
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

    # Destination region -> quick shortlist for Europe, else type
    if cd.startswith("DST_"):
        state["step"] = "DEST_PICK"
        if cd == "DST_EU":
            await query.edit_message_text(
                "Choose a destination (or type):",
                reply_markup=kb([
                    [InlineKeyboardButton("Paris", callback_data="DEST_PARIS"),
                     InlineKeyboardButton("Rome", callback_data="DEST_ROME")],
                    [InlineKeyboardButton("Barcelona", callback_data="DEST_BCN"),
                     InlineKeyboardButton("Amsterdam", callback_data="DEST_AMS")],
                    [InlineKeyboardButton("Type a city", callback_data="DEST_TYPE")],
                ])
            )
        else:
            await query.edit_message_text("Type your destination city/airport:")
            state["step"] = "DEST_TYPED"
        return

    if cd.startswith("DEST_") and cd not in ("DEST_TYPE",):
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

    if cd == "DEST_TYPE":
        await query.edit_message_text("Type your destination city/airport:")
        state["step"] = "DEST_TYPED"
        return

    # Travel window -> priority
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

    # Priority -> price question
    if cd.startswith("PR_"):
        data["priority"] = cd.replace("PR_", "")
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
        # Send final result in next message
        # (We need a dummy query-like object; simplest: send result directly)
        await send_result(update.message, data, is_message=True)
        return

    # If user types randomly
    await update.message.reply_text("Type /check to start a Trip Check, or /help for commands.")


def rule_based_verdict(data: Dict[str, Any]) -> Dict[str, Any]:
    # Very simple MVP rules you can improve later
    window = data.get("window")  # 0_2, 2_6, 1_3, 3P, NS
    pref_priority = (data.get("pref_priority") or "Balanced").lower()
    pref_airport = data.get("pref_airport") or "Any"


    verdict = "WAIT"
    reasons = []
    options = []

    if window == "0_2":
        verdict = "BOOK" if priority in ("FAST", "COMF") else "WAIT"
        reasons.append("Short window: prices can be volatile close to departure.")
        reasons.append("If flexibility exists, shifting mid-week often improves value.")
        options.append("If possible, avoid Fri/Sun departures for better pricing.")
    elif window == "2_6":
        verdict = "BOOK"
        reasons.append("This is typically the best optimisation window for most routes.")
        reasons.append("Mid-week departures usually price better and run smoother.")
        options.append("Check nearby airports for improved value vs convenience.")
    elif window == "1_3":
        verdict = "WAIT"
        reasons.append("Often early for best pricing — good time to plan, not commit.")
        reasons.append("Watch for dips 3–6 weeks before travel on many routes.")
        options.append("If travelling in peak season, book earlier than normal.")
    elif window == "3P":
        verdict = "WAIT"
        reasons.append("Usually too early to lock in the best price (unless peak dates).")
        reasons.append("You’ll often see better value closer to 6–10 weeks out.")
        options.append("If it’s a peak period (summer/holidays), consider booking earlier.")
    else:
        verdict = "WAIT"
        reasons.append("Without dates, the safest move is to check typical booking windows.")
        options.append("Run /when next (coming soon) for the best time to book.")

    # Preference-aware tweaks
    if pref_priority == "cheapest":
        options.insert(0, "Prioritise Tue–Wed travel and avoid Fri–Sun if possible.")
        options.insert(1, f"Use nearby airports where possible (your default: {pref_airport}).")
        reasons.append("Cheapest-first trips benefit most from mid-week timing and flexible airports.")
    elif pref_priority == "fastest":
        options.insert(0, "Prioritise direct routes and shortest connections (even if slightly higher).")
        options.insert(1, "Book earlier in the optimal window to secure the best direct options.")
        reasons.append("Fastest-first trips often require earlier booking to secure direct seats.")
    elif pref_priority == "comfort":
        options.insert(0, "Aim for better departure times (avoid red-eyes if you can).")
        options.insert(1, "Book earlier in the window to secure better flight times and seating.")
        reasons.append("Comfort-first trips benefit from earlier booking and better departure times.")

    # Keep lists tidy
    reasons = reasons[:3]
    options = options[:3]


    return {"verdict": verdict, "reasons": reasons[:3], "options": options[:3]}


async def send_result(obj, data: Dict[str, Any], is_message: bool = False):
    prefs = get_prefs(user_id) if user_id else {"airport": "Any", "priority": "Balanced"}
    data["pref_priority"] = prefs.get("priority", "Balanced")
    data["pref_airport"] = prefs.get("airport", "Any")
    user_id = obj.from_user.id if hasattr(obj, "from_user") else None
    prefs = get_prefs(user_id) if user_id else {"airport": "Any", "priority": "Balanced"}

    # Use preference if user didn't specify a precise airport
    if data.get("departure") in (None, "ANY", "Any", "ANY LONDON"):
        if prefs.get("airport") not in ("Any", "ANY"):
            data["departure"] = prefs["airport"]

    # Use preferred priority if not set
    if data.get("priority") in (None, "", "BAL"):
        pass  # leave as-is for now

    # 👇 existing code continues below
    from_ = data.get("departure")
    to_ = data.get("destination")
    priority = data.get("priority")
    from_ = data.get("departure", "—")
    to_ = data.get("destination", "—")
    trip_type = data.get("trip_type", "—")
    price = data.get("price")
    priority = data.get("priority", "BAL")

    verdict_pack = rule_based_verdict(data)

    price_line = f"\nPrice considered: {price}" if price else ""
    text = (
    "✈️ Airlo Trip Check\n\n"
    "Route\n"
    f"{from_} → {to_}\n"
    f"{trip_type} · {priority.title()} priority\n\n"
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
    "Wait and re-check closer to the optimal booking window"
)


    buttons = kb([
        [InlineKeyboardButton("Run another check 🔁", callback_data="CHECK_START")],
        [InlineKeyboardButton("Set preferences ⚙️", callback_data="SETTINGS_SOON")],
    ])

    if is_message:
        await obj.reply_text(text, parse_mode="Markdown", reply_markup=buttons)
    else:
        await obj.edit_message_text(text, parse_mode="Markdown", reply_markup=buttons)


async def settings_soon(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("⚙️ Preferences are coming next. For now, use /check.")


def main():
    if not TOKEN:
        raise RuntimeError("Missing TELEGRAM_BOT_TOKEN env var.")

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    # app.add_handler(CommandHandler("check", check_cmd))  # disabled until check_cmd exists
    app.add_handler(CommandHandler("when", when_cmd))
    app.add_handler(CommandHandler("settings", settings_cmd))

    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(CallbackQueryHandler(settings_soon, pattern="^SETTINGS_SOON$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_handler(CommandHandler("status", status_cmd))

    app.run_polling()


if __name__ == "__main__":
    main()
