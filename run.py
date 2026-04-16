#!/usr/bin/env python3
"""
Runner script — run from project root: python run.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.main import main

if __name__ == "__main__":
    main()