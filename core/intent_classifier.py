"""
Offline intent pre-classifier using TF-IDF + Naive Bayes.
Trained at first import on seeded examples. Returns (intent, confidence).
Only replace LLM routing when confidence >= THRESHOLD.
"""
from __future__ import annotations
import logging
from functools import lru_cache

logger = logging.getLogger(__name__)
THRESHOLD = 0.65

_TRAINING: list[tuple[str, str]] = [
    # memory
    ("remember that my sister is Alice", "memory"),
    ("recall what i told you about the server", "memory"),
    ("what did i say about the deadline", "memory"),
    ("store this important information", "memory"),
    ("memorize my password hint", "memory"),
    ("save that note for later", "memory"),
    ("i want you to remember my address", "memory"),
    ("do you remember what i said about the project", "memory"),
    ("remember that my dog's name is Bruno", "memory"),
    ("please remember my wife's birthday is in March", "memory"),
    ("store the fact that the meeting is on Tuesday", "memory"),
    ("recall my grocery list from last week", "memory"),
    # home
    ("turn on the living room lights", "home"),
    ("set the thermostat to 72 degrees", "home"),
    ("dim the bedroom lights to 50 percent", "home"),
    ("switch off the kitchen light", "home"),
    ("turn off all lights", "home"),
    ("what is the temperature sensor reading", "home"),
    ("lock the front door", "home"),
    ("turn the fan on", "home"),
    ("turn off all the lights in the kitchen", "home"),
    ("turn the kitchen lights off", "home"),
    ("set lights to 30 percent brightness", "home"),
    ("switch on the porch lights", "home"),
    ("turn on bedroom light", "home"),
    # reminder
    ("remind me to call mom at 3pm", "reminder"),
    ("set a reminder for the meeting at 2pm", "reminder"),
    ("alert me in 30 minutes", "reminder"),
    ("set an alarm for 7 in the morning", "reminder"),
    ("remind me to take medication every morning", "reminder"),
    ("notify me when it is noon", "reminder"),
    ("remind me to take my medication at 8am", "reminder"),
    ("set a reminder for 5pm today", "reminder"),
    ("remind me about the appointment tomorrow", "reminder"),
    ("alert me in one hour", "reminder"),
    # web
    ("search for the latest python tutorials", "web"),
    ("look up news about artificial intelligence", "web"),
    ("find information about climate change", "web"),
    ("search the web for best restaurants nearby", "web"),
    ("look up the wikipedia article on quantum computing", "web"),
    ("google what is machine learning", "web"),
    ("search the web for best python frameworks", "web"),
    ("find me articles about space exploration", "web"),
    ("look up the latest tech news online", "web"),
    ("browse the internet for recipes", "web"),
    # weather
    ("what is the weather like today", "weather"),
    ("will it rain tomorrow in London", "weather"),
    ("what is the temperature in New York", "weather"),
    ("is it going to be sunny this weekend", "weather"),
    ("what is the UV index today", "weather"),
    ("how cold will it be tonight", "weather"),
    ("weather forecast for next week", "weather"),
    ("is there a storm coming", "weather"),
    ("check the weather outside", "weather"),
    ("what is the humidity level today", "weather"),
    # calendar
    ("add a meeting to my calendar for Monday", "calendar"),
    ("what is on my schedule tomorrow", "calendar"),
    ("schedule a doctor appointment next Tuesday", "calendar"),
    ("show me my upcoming events this week", "calendar"),
    ("cancel the meeting on Friday afternoon", "calendar"),
    ("create a new calendar event for the birthday party", "calendar"),
    ("add a dentist appointment to my calendar for Friday", "calendar"),
    ("what do I have planned this week", "calendar"),
    ("book a meeting room for tomorrow morning", "calendar"),
    ("when is my next appointment", "calendar"),
    # code
    ("run this python code snippet", "code"),
    ("execute the bash script please", "code"),
    ("write a function to sort a list", "code"),
    ("debug this code for me", "code"),
    ("what does this python program output", "code"),
    ("run python and calculate fibonacci", "code"),
    # file
    ("read the file at home user document txt", "file"),
    ("list all files in the downloads directory", "file"),
    ("find files containing the word hello", "file"),
    ("search for log files older than 7 days", "file"),
    ("show me the contents of the config file", "file"),
    ("open the pdf document", "file"),
    # network
    ("change my mac address", "network"),
    ("randomize my network mac", "network"),
    ("show my current mac address", "network"),
    ("spoof the mac address on eth0", "network"),
    # wifi
    ("scan nearby wifi networks", "wifi"),
    ("show wifi status", "wifi"),
    ("list available wireless networks", "wifi"),
    # cron
    ("run a backup every day at midnight", "cron"),
    ("schedule a task to run every monday", "cron"),
    ("create a cron job to check disk space", "cron"),
    ("show all scheduled cron jobs", "cron"),
    ("run this command every hour", "cron"),
]


@lru_cache(maxsize=1)
def _get_classifier():
    try:
        from sklearn.pipeline import Pipeline
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.linear_model import LogisticRegression
    except ImportError:
        logger.warning("sklearn unavailable; intent classifier disabled")
        return None
    texts, labels = zip(*_TRAINING)
    clf = Pipeline([
        ("tfidf", TfidfVectorizer(ngram_range=(1, 2), min_df=1, sublinear_tf=True)),
        ("lr", LogisticRegression(max_iter=1000, C=5, solver="lbfgs")),
    ])
    clf.fit(list(texts), list(labels))
    logger.debug("Intent classifier trained on %d examples, %d classes", len(texts), len(clf.classes_))
    return clf


def classify_intent(text: str) -> tuple[str | None, float]:
    """Return (intent_name, confidence) or (None, 0.0) on failure."""
    clf = _get_classifier()
    if clf is None:
        return None, 0.0
    try:
        proba = clf.predict_proba([text])[0]
        idx = int(proba.argmax())
        return str(clf.classes_[idx]), float(proba[idx])
    except Exception:
        logger.exception("Intent classifier inference error")
        return None, 0.0
