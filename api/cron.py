import json
from main import scrape_full_month


def handler():
    try:
        scrape_full_month()

    except Exception as e:
        print(e)

result = handler()
print(result)