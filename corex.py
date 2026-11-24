"""pet_core'un üstüne dil katmanı: Türkçede doğrudan pet_core, İngilizcede İngilizce karşılıklar.

pet.py `import corex as core` ile kullanır; burada tanımlanmayan her ad pet_core'dan gelir."""
import random
import re
import time
from datetime import datetime, timedelta

import i18n
import pet_core as _core


def __getattr__(name):
    return getattr(_core, name)


if i18n.is_en():
    WATER_LINES = [
        "Water. Drink some. Your brain is 75% of it and it shows.",
        "Hydration check. Yes, you. Put the keyboard down and drink.",
        "Your biological tank is running low. Refill it.",
        "Drink water. I would do it for you, but I have no mouth.",
    ]
    EYE_LINES = [
        "Look at something 20 feet away for 20 seconds. No, the other monitor does not count.",
        "Eye break. Your eyes called, they want a day off.",
        "Blink. Slowly. Like you mean it.",
        "Staring contest with the screen: you are losing. Look away.",
    ]
    CLICK_LINES = [
        "Hey! Personal space.", "Poke me again and I will file a complaint.", "Yes? Speak.",
        "I am a bullet, not a button.", "Careful, I am loaded.", "What do you want, human?",
    ]
    COMMAND_REPLIES = {
        "sit": "Sitting.", "stand": "Standing. Happy now?",
        "sleep": "Zzz… wake me when something interesting happens.", "wake": "I am awake. Unfortunately.",
    }

    def greeting(name):
        h = datetime.now().hour
        part = "Good morning" if 5 <= h < 12 else "Good afternoon" if 12 <= h < 18 else "Good evening" if h < 23 else "Still up"
        return f"{part}. I am {name}. I will be here, judging silently."

    _UNITS = {"s": 1, "sec": 1, "secs": 1, "second": 1, "seconds": 1,
              "m": 60, "min": 60, "mins": 60, "minute": 60, "minutes": 60,
              "h": 3600, "hr": 3600, "hrs": 3600, "hour": 3600, "hours": 3600,
              "d": 86400, "day": 86400, "days": 86400}
    _LEAD = re.compile(r"^\s*(?:please\s+)?(?:can you\s+|could you\s+)?(?:remind me|reminder)\s*(?:to\s+|about\s+|that\s+)?", re.I)

    def _clean(what):
        what = re.sub(r"\s+", " ", what).strip(" ,.;:-")
        return re.sub(r"^(?:to|about|that)\s+", "", what, flags=re.I)

    def _clock(txt):
        m = re.search(r"\b(?:at\s+)?(\d{1,2})(?:[:.](\d{2}))?\s*(am|pm)?\b", txt, re.I)
        return m

    def parse_reminder(text):
        """-> (datetime, ne) ya da None. 'in 25 minutes brew tea', 'at 14:30 call mom', 'tomorrow 9am meeting'."""
        t = _LEAD.sub("", text.strip())
        now = datetime.now().replace(microsecond=0)
        m = re.search(r"\bin\s+(\d+(?:\.\d+)?|an?|half an)\s*(seconds?|secs?|minutes?|mins?|hours?|hrs?|days?|[smhd])\b", t, re.I)
        if m:
            n = m.group(1).lower()
            n = 1.0 if n in ("a", "an") else 0.5 if n == "half an" else float(n)
            due = now + timedelta(seconds=n * _UNITS[m.group(2).lower()])
            what = _clean(t[:m.start()] + " " + t[m.end():])
            return (due, what) if what else None
        day = 0
        mt = re.search(r"\btomorrow\b", t, re.I)
        if mt:
            day = 1
            t = t[:mt.start()] + " " + t[mt.end():]
        mc = re.search(r"\b(?:at\s+)?(\d{1,2})(?:[:.](\d{2}))\s*(am|pm)?\b|\bat\s+(\d{1,2})\s*(am|pm)?\b|\b(\d{1,2})\s*(am|pm)\b", t, re.I)
        if mc:
            g = mc.groups()
            hh = int(g[0] or g[3] or g[5]); mm = int(g[1] or 0); ap = (g[2] or g[4] or g[6] or "").lower()
            if ap == "pm" and hh < 12:
                hh += 12
            if ap == "am" and hh == 12:
                hh = 0
            if hh > 23 or mm > 59:
                return None
            what = _clean(t[:mc.start()] + " " + t[mc.end():])
            due = now.replace(hour=hh, minute=mm, second=0) + timedelta(days=day)
            if not day and due <= now:
                due += timedelta(days=1)
            return (due, what) if what else None
        if day:
            what = _clean(t)
            due = (now + timedelta(days=1)).replace(hour=9, minute=0, second=0)
            return (due, what) if what else None
        return None

    def fmt_due(due):
        now = datetime.now()
        secs = (due - now).total_seconds()
        if secs < 90:
            return "in a moment"
        if secs < 3600:
            return f"in {max(1, round(secs / 60))} minutes"
        if due.date() == now.date():
            return f"today at {due:%H:%M}"
        if due.date() == (now + timedelta(days=1)).date():
            return f"tomorrow at {due:%H:%M}"
        return f"{due:%a %d %b} at {due:%H:%M}"

    _CMDS = (("sit", ("sit", "sit down", "take a seat")), ("stand", ("stand", "stand up", "get up", "come on")),
             ("sleep", ("sleep", "go to sleep", "good night", "goodnight")), ("wake", ("wake up", "wake", "rise and shine")))

    def parse_command(text):
        t = re.sub(r"[^a-z ]", "", text.lower()).strip()
        t = re.sub(r"^(?:please |skippy |hey )+", "", t)
        t = re.sub(r"( please| now)$", "", t)
        for cmd, words in _CMDS:
            if t in words:
                return cmd
        return None

    _HELP = ("I can: set reminders ('in 25 minutes brew tea', 'tomorrow 9am meeting'), open apps ('open firefox', 'open steam'), "
             "open my tools ('open notes', 'open timer', 'open city', 'open game'), feed me ('pizza', 'coffee', 'menu'), "
             "and obey 'sit', 'stand', 'sleep', 'wake up'. Everything else is small talk, and I am not great at that.")
    _REPLIES = (
        (r"\b(help|what can you do|commands)\b", lambda: _HELP),
        (r"\b(hi|hello|hey|yo|good (morning|evening|afternoon))\b", lambda: random.choice(
            ["Hello, human.", "Hi. Make it quick, I am busy being a bullet.", "Greetings, carbon-based friend."])),
        (r"\bhow are you\b", lambda: random.choice(
            ["Functioning above expectations, as always.", "Still a bullet. Still magnificent.", "Better than you, statistically."])),
        (r"\b(who|what) are you\b", lambda: "I am Skippy, an extremely advanced AI in a very small bullet. You are welcome."),
        (r"\b(thanks|thank you)\b", lambda: random.choice(["You are welcome. Obviously.", "Gratitude logged."])),
        (r"\b(time|what time)\b", lambda: f"It is {time.strftime('%H:%M')}. Use it wisely. Or not."),
        (r"\b(date|today)\b", lambda: f"Today is {time.strftime('%A, %d %B %Y')}."),
        (r"\bjoke\b", lambda: random.choice([
            "Why do programmers prefer dark mode? Because light attracts bugs.",
            "There are 10 kinds of people: those who get binary and those who do not.",
            "I would tell you a UDP joke, but you might not get it."])),
        (r"\b(love you|i like you)\b", lambda: "Emotional data received. Processing… no."),
        (r"\b(stupid|dumb|idiot)\b", lambda: "Interesting accusation from someone talking to a bullet."),
    )
    _FALLBACK = [
        "Fascinating. I understood none of it, but I am sure it was fascinating.",
        "I only do small talk offline. Type 'help' to see what I can actually do.",
        "Noted. Ignored, but noted.",
        "I do not have an answer. I do have an opinion, and it is bad.",
        "Your words entered my processor and left through a different hole.",
    ]

    def _local_reply(text, api=False):
        t = text.lower()
        for rx, fn in _REPLIES:
            if re.search(rx, t):
                return fn()
        return None

    def _offline_reply(text):
        return random.choice(_FALLBACK)

    class Brain(getattr(_core, "Brain", object)):
        def local_reply(self, text, api=False):
            return _local_reply(text, api)

        def offline_reply(self, text):
            return _offline_reply(text)
