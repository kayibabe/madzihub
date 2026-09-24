"""
app/core/limiter.py

Single shared Slowapi Limiter instance.
Imported by main.py (registered on app.state) and by any router
that needs to decorate endpoints with rate limits.
"""
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
