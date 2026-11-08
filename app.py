# -*- coding: utf-8 -*-
"""
Arduino Block Studio & Universal Web Entry Point
相容 Render, Heroku, Waitress, Gunicorn 等 WSGI 部署環境
"""
import os
import sys

from block_studio import app, main

# Render / WSGI 標準應用入口變數: app, application
application = app

if __name__ == "__main__":
    main()

