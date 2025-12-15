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

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# --- Simple per-user state store (MVP) ---
# In production you'd use a database, but for V1 this is enough.
USER_STATE: Dict[int, Dict[str, Any]] = {}

# --- Helpers ---
def get_state(user_id: int) -> Dict[str, Any]:
    if user_id not in USER_STATE:
        USER_STATE[user_id] = {"step": None, "data": {}}
    return USER_STATE[user_id]

def reset_check(user_id: int):
    USER_STATE[user_id] = {"step": "CHECK_ENTRY", "data": {}}

def kb(rows):
    return InlineKeyboardMarkup(rows)

# --- Command: /start ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "✈️ Welcome to *Airlo*\n\n"
        "Airlo helps you make smarter travel decisions *before you book*.\n\n"
        "Start with /check"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

# --- Command: /help ---
async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "Available commands:\n\n"
        "/check — Sense-check a trip before booking\n"
        "/when — Best time to book (coming next)\n"
        "/settings — Preferences (coming next)\n"
        "/help — This menu"
    )
    await update.message.reply_text(text)

# --- Command: /check (Entry screen) ---
async def check_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        state["step"] = "TRIP_TYPE"
        await query.edit_message_text(
            "What type of trip is this?",
            reply_markup=kb([
                [InlineKeyboardButton("Return 🔁", callback_data="TRIP_RETURN")],
                [InlineKeyboardButton("One-way ✈️", callback_data="TRIP_ONEWAY")],
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
    window = data.get("window")  # "0_2", "2_6", "1_3", "3P", "NS"
    priority = data.get("priority")  # CHEAP, BAL, FAST, COMF

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

    return {"verdict": verdict, "reasons": reasons[:3], "options": options[:3]}


async def send_result(obj, data: Dict[str, Any], is_message: bool = False):
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
    app.add_handler(CommandHandler("check", check_cmd))

    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(CallbackQueryHandler(settings_soon, pattern="^SETTINGS_SOON$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    app.run_polling()


if __name__ == "__main__":
    main()
