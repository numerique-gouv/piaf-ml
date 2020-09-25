"""
Ths file splits a text file containing the fiches raw text into two files: train.txt and test.txt.
To use it, pass a percentage of the desired size for the train
"""

from pathlib import Path
import sys

if len(sys.argv) < 2:
    print("Please indicate the train %. Exiting...")
    exit()

TRAIN_PCT = float(sys.argv[1])

path_file = Path("all_fiches.txt")
file_size = path_file.stat().st_size
train_size = int(file_size * TRAIN_PCT)
with open("all_fiches.txt") as fiches:
    train_content = fiches.read(train_size)
    test_content = fiches.read()
with open("train_fiches.txt", "w") as out:
    out.write(train_content)
with open("test_fiches.txt", "w") as out:
    out.write(test_content)