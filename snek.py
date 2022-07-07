import os

import inflection
from rich import print
from textblob import TextBlob
from toolz import unique

targets = [('docs', '.rst'), ('examples', '.vy')]

for dir, ext in targets:
    for root, dirs, files in os.walk(dir):
        for file in files:
            if not file.endswith(ext):
                continue
            print(f"[green]{file}")
            source = open(f"{root}/{file}").read()
            text = TextBlob(source)
            for word in unique(text.words):
                is_camel = word == inflection.camelize(word, False).replace("-", "")
                is_snek = word == inflection.underscore(word)
                if is_camel and not is_snek:
                    print(f"  {word} -> {inflection.underscore(word)}")
                    source = source.replace(word, inflection.underscore(word))

            open(f"{root}/{file}", "wt").write(source)
