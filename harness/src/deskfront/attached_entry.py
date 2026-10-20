"""Standalone public Harness entry: talks only to an already running game SDK."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'sdk/python'))
from quickplay import Game
from attached_host import run

if __name__ == '__main__':run(Game())
