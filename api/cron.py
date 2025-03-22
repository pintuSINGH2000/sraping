import json
from main import scrape_full_month


def handler():
    try:
        scrape_full_month()
        return res.json({"message": result})

    except Exception as e:
        return res.json({"message": f"Error: {str(e)}"}, status=500)

result = handler()
print(result)