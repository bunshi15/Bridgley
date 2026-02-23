# app/core/bots/moving_bot_v1/config.py
"""
Configuration for the Moving/Delivery Bot.
This is a concrete implementation using the universal bot system.
"""
from app.core.bot_types import (
    BotConfig, Intent, IntentPatterns, Translation,
    MovingBotStep, MovingTimeWindow, MovingExtraService,
    MovingDateChoice, MovingTimeSlot,
)


# ============================================================================
# INTENT PATTERNS (Moving Bot)
# ============================================================================

MOVING_INTENT_PATTERNS = {
    Intent.RESET: IntentPatterns(
        ru={"заново", "сначала", "рестарт", "перезапуск", "/start", "start"},
        en={"reset", "restart", "start", "/start"},
        he={"התחל", "מחדש", "ריסט"}
    ),
    Intent.CONFIRM: IntentPatterns(
        ru={"готово", "всё", "все", "закончено", "да", "ага"},
        en={"done", "finish", "finished", "yes", "yep"},
        he={"סיימתי", "גמרתי", "סיום", "סיימנו", "כן"}
    ),
    Intent.DECLINE: IntentPatterns(
        ru={"нет", "неа", "не нужно"},
        en={"no", "nope", "skip"},
        he={"לא"}
    ),
}


# ============================================================================
# TRANSLATIONS (Moving Bot Messages)
# ============================================================================

MOVING_TRANSLATIONS = {
    # Welcome and questions
    "welcome": Translation(
        ru="Привет! 👋\nЯ помогу быстро оформить заявку на перевозку.\nЗадам пару вопросов — это займёт 1–2 минуты.",
        en="Hello! 👋\nI'll help you quickly arrange a move.\nI'll ask a few questions — it will take 1-2 minutes.",
        he="שלום! 👋\nאני אעזור לך לארגן העברה במהירות.\nאשאל כמה שאלות - זה ייקח 1-2 דקות."
    ),

    "welcome_contact": Translation(
        ru="📞 Связаться с оператором: {phone}",
        en="📞 Contact operator: {phone}",
        he="📞 ליצירת קשר עם המפעיל: {phone}"
    ),

    "q_cargo": Translation(
        ru="Что нужно перевезти?\nМожно коротко или списком.",
        en="What needs to be moved?\nBrief description or list.",
        he="מה צריך להעביר?\nתיאור קצר או רשימה."
    ),

    "q_addr_from": Translation(
        ru="Откуда забираем?\nНапишите адрес или район текстом\nили укажите на карте точку геолокации",
        en="Where do we pick up from?\nType an address or district\nor share a map location pin",
        he="מאיפה אוספים?\nכתוב כתובת או אזור\nאו שלח נקודת מיקום במפה"
    ),

    "q_floor_from": Translation(
        ru="Какой этаж и есть ли лифт на месте загрузки?",
        en="What floor and is there an elevator at the pickup?",
        he="באיזו קומה ויש מעלית בנקודת האיסוף?"
    ),

    "q_addr_to": Translation(
        ru="Куда доставляем?\nНапишите адрес или район текстом\nили укажите на карте точку геолокации",
        en="Where do we deliver to?\nType an address or district\nor share a map location pin",
        he="לאן מוסרים?\nכתוב כתובת או אזור\nאו שלח נקודת מיקום במפה"
    ),

    "q_floor_to": Translation(
        ru="Какой этаж и есть ли лифт на месте выгрузки?",
        en="What floor and is there an elevator at the delivery?",
        he="באיזו קומה ויש מעלית בנקודת המסירה?"
    ),

    "q_time": Translation(
        ru="Когда планируется перевозка?\n1 — сегодня\n2 — завтра\n3 — в ближайшие дни\nили напишите дату/время текстом.",
        en="When is the move planned?\n1 — today\n2 — tomorrow\n3 — in the next few days\nor write the date/time as text.",
        he="מתי מתוכנן המעבר?\n1 — היום\n2 — מחר\n3 — בימים הקרובים\nאו כתוב את התאריך/שעה בטקסט."
    ),

    "q_photo_menu": Translation(
        ru="Фото груза есть?\n1 — Да, отправлю фото\n2 — Нет фото",
        en="Do you have photos?\n1 — Yes, I'll send photos\n2 — No photos",
        he="יש לך תמונות?\n1 — כן, אני אשלח תמונות\n2 — אין תמונות"
    ),

    "q_photo_menu_rooms": Translation(
        ru="Для переезда из квартиры фото помогут нам дать точную оценку! 📸\n1 — Да, отправлю фото\n2 — Нет фото",
        en="For apartment moves, photos help us give a much more accurate estimate! 📸\n1 — Yes, I'll send photos\n2 — No photos",
        he="להעברת דירה, תמונות עוזרות לנו לתת הערכה מדויקת יותר! 📸\n1 — כן, אני אשלח תמונות\n2 — אין תמונות"
    ),

    "ack_landing_prefill": Translation(
        ru="Спасибо за заявку с сайта! 👋\nЯ уже получил ваши данные. Уточню пару деталей.",
        en="Thanks for the website inquiry! 👋\nI've got your details. Let me confirm a few things.",
        he="תודה על הפנייה מהאתר! 👋\nקיבלתי את הפרטים. אוודא כמה דברים.",
    ),

    "q_confirm_addresses": Translation(
        ru="Вы указали:\n📍 Откуда: {addr_from}\n📍 Куда: {addr_to}\n\nХотите уточнить адреса (улица, дом, этаж)?\n1 — Да, уточню адреса\n2 — Нет, продолжить без уточнения",
        en="You provided:\n📍 From: {addr_from}\n📍 To: {addr_to}\n\nWould you like to specify full addresses (street, building, floor)?\n1 — Yes, I'll provide details\n2 — No, continue without",
        he="ציינת:\n📍 מ: {addr_from}\n📍 אל: {addr_to}\n\nרוצה לפרט כתובות מלאות (רחוב, בניין, קומה)?\n1 — כן, אפרט\n2 — לא, להמשיך בלי",
    ),

    "err_confirm_addresses": Translation(
        ru="Выбери: 1 — уточнить адреса, 2 — продолжить.",
        en="Please choose: 1 — specify addresses, 2 — continue.",
        he="אנא בחר: 1 — לפרט כתובות, 2 — להמשיך.",
    ),
    "err_rejected_input": Translation(
        ru="Не удалось обработать сообщение. Пожалуйста, отправьте текст без ссылок.",
        en="Could not process the message. Please send text without links.",
        he="לא ניתן לעבד את ההודעה. אנא שלח טקסט ללא קישורים.",
    ),

    "q_photo_wait": Translation(
        ru="Ок, пришлите фото одним или несколькими сообщениями.\nКогда закончите — напишите «готово».",
        en="OK, send photos in one or more messages.\nWhen finished — write \"done\".",
        he="אוקיי, שלח תמונות בהודעה אחת או יותר.\nכשתסיים - כתוב \"סיימתי\"."
    ),

    "q_extras": Translation(
        ru="Нужны доп. услуги?\n1 — грузчики\n2 — сборка/разборка\n3 — упаковка\n4 — ничего из этого\nМожно выбрать несколько: 1 3\nИли с комментарием, пример: 1 3 + нет парковки\nИли только текст с деталями.",
        en="Need extra services?\n1 — loaders\n2 — assembly/disassembly\n3 — packing\n4 — none of these\nCan choose multiple: 1 3\nOr with comment: 1 3 + 5th floor, no elevator\nOr just text with details.",
        he="צריך שירותים נוספים?\n1 — סבלים\n2 — הרכבה/פירוק\n3 — אריזה\n4 — אף אחד מאלה\nאפשר לבחור כמה: 1 3\nאו עם הערה: 1 3 + קומה 5, בלי מעלית\nאו רק טקסט עם פרטים."
    ),

    "done": Translation(
        ru="Спасибо! Я передал информацию оператору, он скоро свяжется с вами 👍",
        en="Thank you! I've sent the information to the operator, they will contact you soon 👍",
        he="תודה! העברתי את המידע למפעיל, הוא ייצור איתך קשר בקרוב 👍"
    ),

    # Errors
    "err_cargo_too_short": Translation(
        ru="Можешь чуть подробнее? Например: «диван, холодильник, коробки».",
        en="Can you be more specific? For example: \"sofa, fridge, boxes\".",
        he="אתה יכול להיות יותר ספציפי? למשל: \"ספה, מקרר, קרטונים\"."
    ),

    "err_addr_too_short": Translation(
        ru="Подскажи хотя бы город или район. Например: «Tel Aviv, ул. Дизенгоф 50».",
        en="Please provide at least a city or district. For example: \"Tel Aviv, 50 Dizengoff St\".",
        he="אנא ספק לפחות עיר או אזור. למשל: \"תל אביב, דיזנגוף 50\"."
    ),

    "err_floor_too_short": Translation(
        ru="Напиши хотя бы этаж, например: «3 этаж, лифт есть» или «частный дом».",
        en="Please provide at least the floor, e.g.: \"3rd floor, elevator available\" or \"private house\".",
        he="אנא ציין לפחות את הקומה, למשל: \"קומה 3, יש מעלית\" או \"בית פרטי\"."
    ),

    "err_time_format": Translation(
        ru="Можно так: «завтра после 18», «в пятницу утром» или выбери 1/2/3.",
        en="You can say: \"tomorrow after 6pm\", \"Friday morning\" or choose 1/2/3.",
        he="אתה יכול לומר: \"מחר אחרי 18:00\", \"יום שישי בבוקר\" או בחר 1/2/3."
    ),

    "err_photo_menu": Translation(
        ru="Можно выбрать:\n1 — отправлю фото\n2 — нет фото",
        en="You can choose:\n1 — I'll send photos\n2 — no photos",
        he="אתה יכול לבחור:\n1 — אני אשלח תמונות\n2 — אין תמונות"
    ),

    "err_extras_empty": Translation(
        ru="Если ничего не нужно — напиши «нет». Иначе опиши детали в одном сообщении.",
        en="If nothing is needed — write \"no\". Otherwise describe details in one message.",
        he="אם אין צורך בכלום - כתוב \"לא\". אחרת תאר פרטים בהודעה אחת."
    ),

    # Info messages
    "info_photo_wait": Translation(
        ru="Пришли фото сообщениями. Когда закончишь — напиши «готово».",
        en="Send photos in messages. When finished — write \"done\".",
        he="שלח תמונות בהודעות. כשתסיים - כתוב \"סיימתי\"."
    ),

    "info_photo_received_first": Translation(
        ru="Фото получил 👍 Пришли ещё, если нужно. Когда закончишь — напиши «готово».",
        en="Photo received 👍 Send more if needed. When finished — write \"done\".",
        he="תמונה התקבלה 👍 שלח עוד אם צריך. כשתסיים - כתוב \"סיימתי\"."
    ),

    "info_photo_received_late": Translation(
        ru="Фото получил 👍 Если хочешь оформить заявку заново — напиши «заново».",
        en="Photo received 👍 If you want to start over — write \"reset\".",
        he="תמונה התקבלה 👍 אם אתה רוצה להתחיל מחדש - כתוב \"מחדש\"."
    ),

    "info_already_done": Translation(
        ru="Заявка уже оформлена. Если нужно — напишите уточнение.",
        en="Request already completed. If needed — write clarification.",
        he="הבקשה כבר הושלמה. אם צריך - כתוב הבהרה."
    ),

    "hint_can_reset": Translation(
        ru="Если хочешь начать заново — напиши «заново».",
        en="If you want to start over — write \"reset\".",
        he="אם אתה רוצה להתחיל מחדש - כתוב \"מחדש\"."
    ),

    "hint_stale_resume": Translation(
        ru="У тебя есть незавершённая заявка. Можешь продолжить или написать «заново» чтобы начать сначала.",
        en="You have an unfinished request. You can continue or write \"reset\" to start over.",
        he="יש לך בקשה שלא הושלמה. אתה יכול להמשיך או לכתוב \"מחדש\" כדי להתחיל מחדש."
    ),

    # Phase 2: structured scheduling
    "q_date": Translation(
        ru="Когда планируется перевозка?\n1 — завтра\n2 — через 2–3 дня\n3 — в течение недели\n4 — выбрать конкретную дату",
        en="When is the move planned?\n1 — tomorrow\n2 — in 2-3 days\n3 — within the next week\n4 — choose specific date",
        he="מתי מתוכנן המעבר?\n1 — מחר\n2 — בעוד 2-3 ימים\n3 — במהלך השבוע\n4 — בחר תאריך ספציפי"
    ),

    "q_specific_date": Translation(
        ru="Укажите дату в формате ДД.ММ или ДД.ММ.ГГГГ\nНапример: 25.03 или 25.03.2026",
        en="Enter the date in DD.MM or DD.MM.YYYY format\nFor example: 25.03 or 25.03.2026",
        he="הזן את התאריך בפורמט DD.MM או DD.MM.YYYY\nלדוגמה: 25.03 או 25.03.2026"
    ),

    "q_time_slot": Translation(
        ru="В какое время удобно?\n1 — утро (08:00–12:00)\n2 — день (12:00–16:00)\n3 — вечер (16:00–20:00)\n4 — точное время\n5 — пока не знаю",
        en="What time works for you?\n1 — morning (08:00-12:00)\n2 — afternoon (12:00-16:00)\n3 — evening (16:00-20:00)\n4 — exact time\n5 — not sure yet",
        he="מתי נוח לך?\n1 — בוקר (08:00-12:00)\n2 — צהריים (12:00-16:00)\n3 — ערב (16:00-20:00)\n4 — שעה מדויקת\n5 — עדיין לא יודע"
    ),

    "q_exact_time": Translation(
        ru="Напишите время в формате ЧЧ:ММ (24-часовой)\nНапример: 14:30",
        en="Write the time in HH:MM format (24-hour)\nFor example: 14:30",
        he="כתוב את השעה בפורמט HH:MM (24 שעות)\nלדוגמה: 14:30"
    ),

    "err_date_choice": Translation(
        ru="Выбери вариант: 1, 2, 3 или 4.",
        en="Please choose an option: 1, 2, 3, or 4.",
        he="אנא בחר אפשרות: 1, 2, 3 או 4."
    ),

    "err_date_format": Translation(
        ru="Не могу разобрать дату. Напиши в формате ДД.ММ или ДД.ММ.ГГГГ\nНапример: 25.03 или 25.03.2026",
        en="Can't parse the date. Please use DD.MM or DD.MM.YYYY format\nFor example: 25.03 or 25.03.2026",
        he="לא מצליח לפענח את התאריך. אנא השתמש בפורמט DD.MM או DD.MM.YYYY\nלדוגמה: 25.03 או 25.03.2026"
    ),

    "err_date_invalid": Translation(
        ru="Такой даты не существует. Проверь и попробуй ещё раз.",
        en="This date doesn't exist. Please check and try again.",
        he="התאריך הזה לא קיים. אנא בדוק ונסה שוב."
    ),

    "err_date_too_soon": Translation(
        ru="Перевозка возможна не ранее чем завтра. Укажи другую дату.",
        en="The earliest possible date is tomorrow. Please choose another date.",
        he="התאריך המוקדם ביותר הוא מחר. אנא בחר תאריך אחר."
    ),

    "err_date_too_far": Translation(
        ru="Слишком далёкая дата (максимум 90 дней). Укажи другую дату.",
        en="The date is too far in the future (max 90 days). Please choose another date.",
        he="התאריך רחוק מדי (מקסימום 90 ימים). אנא בחר תאריך אחר."
    ),

    "err_time_slot_choice": Translation(
        ru="Выбери вариант: 1, 2, 3, 4 или 5.",
        en="Please choose an option: 1, 2, 3, 4, or 5.",
        he="אנא בחר אפשרות: 1, 2, 3, 4 או 5."
    ),

    "err_exact_time_format": Translation(
        ru="Не могу разобрать время. Напиши в формате ЧЧ:ММ, например: 14:30",
        en="Can't parse the time. Please use HH:MM format, e.g.: 14:30",
        he="לא מצליח לפענח את השעה. אנא השתמש בפורמט HH:MM, למשל: 14:30"
    ),

    # Phase 3: pricing estimate
    "estimate_summary": Translation(
        ru="📋 Примерная стоимость перевозки:\n💰 {min_price}–{max_price} ₪\n\nЭто предварительная оценка. Точная цена будет согласована с исполнителем.\n\nВсё верно? Отправляем заявку?\n1 — Да, отправить\n2 — Начать заново",
        en="📋 Estimated moving cost:\n💰 {min_price}–{max_price} ₪\n\nThis is a preliminary estimate. The exact price will be agreed with the mover.\n\nIs everything correct? Submit the request?\n1 — Yes, submit\n2 — Start over",
        he="📋 עלות משוערת להעברה:\n💰 {min_price}–{max_price} ₪\n\nזהו אומדן ראשוני. המחיר המדויק יסוכם עם המוביל.\n\nהכל נכון? שולחים את הבקשה?\n1 — כן, שלח\n2 — התחל מחדש"
    ),

    "estimate_no_price": Translation(
        ru="📋 Мы не смогли точно рассчитать стоимость по описанию.\n\nНаш менеджер свяжется с вами для уточнения.\n\nОтправляем заявку?\n1 — Да, отправить\n2 — Начать заново",
        en="📋 We couldn't calculate an accurate estimate from the description.\n\nOur manager will contact you for details.\n\nSubmit the request?\n1 — Yes, submit\n2 — Start over",
        he="📋 לא הצלחנו לחשב הערכה מדויקת מהתיאור.\n\nהמנהל שלנו ייצור איתך קשר לפרטים.\n\nשולחים את הבקשה?\n1 — כן, שלח\n2 — התחל מחדש",
    ),

    "err_estimate_choice": Translation(
        ru="Выбери: 1 — отправить заявку, 2 — начать заново.",
        en="Please choose: 1 — submit request, 2 — start over.",
        he="אנא בחר: 1 — שלח בקשה, 2 — התחל מחדש."
    ),

    # Phase 4: multi-pickup
    # Phase 9: volume category
    "q_volume": Translation(
        ru="Какой примерный объём перевозки?\n1 — маленький (до 1 м³, пара сумок/коробок)\n2 — средний (1–3 м³, несколько предметов мебели)\n3 — большой (3–10 м³, комната или студия)\n4 — очень большой (10+ м³, квартира целиком)",
        en="What is the approximate volume of the move?\n1 — small (up to 1 m³, a couple of bags/boxes)\n2 — medium (1-3 m³, several pieces of furniture)\n3 — large (3-10 m³, a room or studio)\n4 — extra large (10+ m³, entire apartment)",
        he="מה הנפח המשוער של ההעברה?\n1 — קטן (עד 1 מ״ק, כמה תיקים/קרטונים)\n2 — בינוני (1-3 מ״ק, כמה פריטי ריהוט)\n3 — גדול (3-10 מ״ק, חדר או סטודיו)\n4 — גדול מאוד (10+ מ״ק, דירה שלמה)"
    ),

    "err_volume_choice": Translation(
        ru="Выбери вариант: 1, 2, 3 или 4.",
        en="Please choose an option: 1, 2, 3, or 4.",
        he="אנא בחר אפשרות: 1, 2, 3 או 4."
    ),

    "q_pickup_count": Translation(
        ru="Сколько точек забора?\n1 — одна\n2 — две\n3 — три",
        en="How many pickup locations?\n1 — one\n2 — two\n3 — three",
        he="כמה נקודות איסוף?\n1 — אחת\n2 — שתיים\n3 — שלוש"
    ),

    "err_pickup_count": Translation(
        ru="Выбери: 1, 2 или 3.",
        en="Please choose: 1, 2, or 3.",
        he="אנא בחר: 1, 2 או 3."
    ),

    "q_addr_from_n": Translation(
        ru="📍 Адрес точки забора #{n}:\n(адрес или район)",
        en="📍 Pickup location #{n} address:\n(address or district)",
        he="📍 כתובת נקודת איסוף #{n}:\n(כתובת או אזור)"
    ),

    "q_floor_from_n": Translation(
        ru="Этаж и лифт на точке забора #{n}:",
        en="Floor and elevator at pickup #{n}:",
        he="קומה ומעלית בנקודת איסוף #{n}:"
    ),

    # Phase 5: geo location support
    "info_location_saved": Translation(
        ru="📍 Геолокация получена.",
        en="📍 Location received.",
        he="📍 מיקום התקבל."
    ),
    "info_location_ignored": Translation(
        ru="📍 Отправка геолокации на этом шаге не поддерживается. Пожалуйста, отправьте текстом.",
        en="📍 Location sharing is not supported at this step. Please type your answer.",
        he="📍 שליחת מיקום לא נתמכת בשלב זה. אנא כתוב את תשובתך."
    ),
}


# ============================================================================
# CHOICE LABELS (for displaying options)
# ============================================================================

TIME_WINDOW_LABELS = {
    MovingTimeWindow.TODAY.value: Translation(
        ru="сегодня",
        en="today",
        he="היום"
    ),
    MovingTimeWindow.TOMORROW.value: Translation(
        ru="завтра",
        en="tomorrow",
        he="מחר"
    ),
    MovingTimeWindow.SOON.value: Translation(
        ru="в ближайшие дни",
        en="in the next few days",
        he="בימים הקרובים"
    ),
}

EXTRA_SERVICE_LABELS = {
    MovingExtraService.LOADERS.value: Translation(
        ru="грузчики",
        en="loaders",
        he="סבלים"
    ),
    MovingExtraService.ASSEMBLY.value: Translation(
        ru="сборка/разборка",
        en="assembly/disassembly",
        he="הרכבה/פירוק"
    ),
    MovingExtraService.PACKING.value: Translation(
        ru="упаковка",
        en="packing",
        he="אריזה"
    ),
    MovingExtraService.NONE.value: Translation(
        ru="нет",
        en="none",
        he="אין"
    ),
}


# ============================================================================
# CHOICE MAPPINGS (user input -> enum value)
# ============================================================================

TIME_CHOICES = {
    "1": MovingTimeWindow.TODAY.value,
    "2": MovingTimeWindow.TOMORROW.value,
    "3": MovingTimeWindow.SOON.value,
}

EXTRA_CHOICES = {
    "1": MovingExtraService.LOADERS.value,
    "2": MovingExtraService.ASSEMBLY.value,
    "3": MovingExtraService.PACKING.value,
    "4": MovingExtraService.NONE.value,
}

# Phase 9: volume category choices
VOLUME_CHOICES = {
    "1": "small",
    "2": "medium",
    "3": "large",
    "4": "xl",
}

# Phase 2: structured scheduling choices
DATE_CHOICES = {
    "1": MovingDateChoice.TOMORROW.value,
    "2": MovingDateChoice.IN_2_3_DAYS.value,
    "3": MovingDateChoice.THIS_WEEK.value,
    "4": MovingDateChoice.SPECIFIC.value,
}

TIME_SLOT_CHOICES = {
    "1": MovingTimeSlot.MORNING.value,
    "2": MovingTimeSlot.AFTERNOON.value,
    "3": MovingTimeSlot.EVENING.value,
    "4": MovingTimeSlot.EXACT.value,
    "5": MovingTimeSlot.FLEXIBLE.value,
}


# ============================================================================
# BOT CONFIGURATION
# ============================================================================

MOVING_BOT_CONFIG = BotConfig(
    bot_id="moving_bot_v1",
    name=Translation(
        ru="Бот для оформления заявок на перевозку грузов",
        en="Moving Bot",
        he="בוט להעברות"
    ),
    description=Translation(
        ru="Помогает оформить заявку на перевозку грузов",
        en="Helps arrange cargo moving requests",
        he="עוזר לארגן בקשות להעברת מטענים"
    ),

    # Flow configuration
    step_enum=MovingBotStep,
    initial_step=MovingBotStep.WELCOME.value,
    final_step=MovingBotStep.DONE.value,

    # Intent patterns
    intent_patterns=MOVING_INTENT_PATTERNS,

    # Translations
    translations=MOVING_TRANSLATIONS,

    # Choices
    choices={
        "time": TIME_CHOICES,
        "date": DATE_CHOICES,
        "time_slot": TIME_SLOT_CHOICES,
        "extras": EXTRA_CHOICES,
    },
    choice_labels={
        "time": TIME_WINDOW_LABELS,
        "extras": EXTRA_SERVICE_LABELS,
    },
)
