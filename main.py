import requests
from bs4 import BeautifulSoup
import os
import random
import time
import re
import json
from fastapi import FastAPI
from supabase import create_client
from dotenv import load_dotenv
from datetime import datetime, timedelta
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from dateutil import parser

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

app = FastAPI()

HEADERS = {"User-Agent": "Mozilla/5.0"}

TEST_MODE = True

scraping_urls = [
    "https://austin.kidsoutandabout.com",
]

BASE_URL = "https://www.activityhero.com"

ACTIVITYHERO_URL = (
    BASE_URL
    + "/search?view=activity&q=&location=Palo+Alto%2C+CA&radius=50&activity_types=event"
)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/91.0.4472.124 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/91.0.4472.124 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/91.0.4472.114 Safari/537.36",
]

GALILEO_BASE_URL = "https://galileo-camps.com"
CAMPS_FINDER_URL = f"{GALILEO_BASE_URL}/camp-finder/"


def get_dates_for_current_month():
    today = datetime.today()
    start_of_month = datetime(today.year, today.month, 1)
    next_month = start_of_month.replace(month=(today.month % 12) + 1, day=1)
    num_days = (next_month - start_of_month).days
    limit_days = 2 if TEST_MODE else num_days
    return [
        (start_of_month + timedelta(days=i)).strftime("%Y-%m-%d")
        for i in range(limit_days)
    ]


def extract_start_end_time(time_text):
    if not time_text or time_text.lower() in ["varies", "see website", "all day"]:
        return time_text, time_text
    time_text = time_text.lower().strip()
    time_pattern = re.search(
        r"(\d{1,2}:\d{2}\s*[apmAPM]*)\s*-\s*(\d{1,2}:\d{2}\s*[apmAPM]*)", time_text
    )
    if time_pattern:
        return time_pattern.group(1).strip(), time_pattern.group(2).strip()
    single_time_pattern = re.search(r"(\d{1,2}:\d{2}\s*[apmAPM]*)", time_text)
    if single_time_pattern:
        return single_time_pattern.group(1), "No End Time"
    return "Unparsed Time", "Unparsed Time"


# Scrape event details page
def scrape_event_details(event_url):
    if not event_url:
        return {"email": "No Email", "price": 0.0}

    response = requests.get(event_url, headers=HEADERS)

    if response.status_code != 200:
        return {"email": "No Email", "price": 0.0}

    soup = BeautifulSoup(response.text, "html.parser")

    # Extract email
    email_element = soup.select_one(".field-name-field-email-address a[href^='mailto']")
    email = email_element.text.strip() if email_element else "No Email"

    # Extract Price
    price_element = soup.select_one(".field-name-field-price .field-item")
    price = 0.0
    if price_element:
        extracted_price = re.findall(r"\d+\.\d+|\d+", price_element.text.strip())
        price = float(extracted_price[0]) if extracted_price else 0.0

    # Extract Age Groups
    age_elements = soup.select(
        ".field-name-field-ages.field-type-entityreference.field-label-above"
    )
    ages = (
        [age.text.strip() for age in age_elements]
        if age_elements
        else ["Unknown Age Group"]
    )

    # Extract Tags
    tag_elements = soup.select(
        ".field-name-field-activity-type.field-type-entityreference.field-label-hidden a"
    )
    tags = [tag.text.strip() for tag in tag_elements] if tag_elements else ["No Tags"]

    return {"email": email, "price": price, "ages": ages, "tags": tags}


@app.get("/scrape-month")
def scrape_full_month():
    """Scrapes events for the current month or the first 5 days if TEST_MODE is enabled."""
    all_events = []

    for event_date in get_dates_for_current_month():
        url = f"https://austin.kidsoutandabout.com/event-list/{event_date}"
        print(f"Scraping events from: {url}")  # ✅ Debugging Line

        response = requests.get(url, headers=HEADERS)

        if response.status_code == 200:
            soup = BeautifulSoup(response.text, "html.parser")
            event_items = soup.select("div.node-activity")

            for event in event_items:
                # Extract Event Title

                print("DEBUG: FULL EVENT HTML")
                print(event.prettify())  # Shows properly formatted HTML
                title_element = event.select_one("h2 a")
                event_url = (
                    f"https://austin.kidsoutandabout.com{title_element['href']}"
                    if title_element
                    else None
                )
                # If `<h2><a></a></h2>` is empty, check inside `.group-activity-details`
                if title_element and title_element.text.strip():
                    title = title_element.text.strip()
                else:
                    # Search for the title inside `group-activity-details` as a backup
                    backup_title_element = event.select_one(
                        ".group-activity-details h2 a"
                    )
                    title = (
                        backup_title_element.text.strip()
                        if backup_title_element
                        else "No Title"
                    )

                # Extract Organization
                org_element = event.find("div", class_="address-org-name")
                organization = (
                    org_element.find("span", class_="fn").text.strip()
                    if org_element
                    else "No Organization"
                )

                # Extract Location
                location_element = event.find("div", class_="adr")
                location = {
                    "street": (
                        location_element.find(
                            "div", class_="street-address"
                        ).text.strip()
                        if location_element
                        and location_element.find("div", class_="street-address")
                        else "No Street Address"
                    ),
                    "city": (
                        location_element.find("span", class_="locality").text.strip()
                        if location_element
                        and location_element.find("span", class_="locality")
                        else "No City"
                    ),
                    "state": (
                        location_element.find("span", class_="region").text.strip()
                        if location_element
                        and location_element.find("span", class_="region")
                        else "No State"
                    ),
                    "postal_code": (
                        location_element.find("span", class_="postal-code").text.strip()
                        if location_element
                        and location_element.find("span", class_="postal-code")
                        else "No Postal Code"
                    ),
                    "country": (
                        location_element.find("div", class_="country-name").text.strip()
                        if location_element
                        and location_element.find("div", class_="country-name")
                        else "No Country"
                    ),
                    "google_maps": (
                        location_element.find("a")["href"]
                        if location_element and location_element.find("a")
                        else "No Map Link"
                    ),
                }

                # Extract Dates
                date_elements = event.select(
                    "div.field-type-datetime span.date-display-single"
                )
                dates = (
                    [d.text.strip() for d in date_elements]
                    if date_elements
                    else ["No Date"]
                )

                # Extract Time
                time_element = event.find("div", class_="field-name-field-time")
                raw_time = (
                    time_element.text.replace("Time:", "").strip()
                    if time_element
                    else "No Time"
                )
                start_time, end_time = extract_start_end_time(raw_time)

                # Extract Phone
                phone_element = event.select_one(".tel .value")
                phone = phone_element.text.strip() if phone_element else "No Phone"

                # Extract Image URL
                image_element = event.select_one(
                    "div.field-name-field-enhanced-activity-image img"
                )
                image_url = image_element["src"] if image_element else "No Image"

                # Extract Description
                desc_element = event.select_one(
                    "div.field-name-field-short-description div.field-items"
                )
                description = (
                    desc_element.text.strip() if desc_element else "No Description"
                )

                # Fetch email and price from the event's detail page
                extra_details = scrape_event_details(event_url) if event_url else {}
                ages = extra_details.get("ages", ["Unknown Age Group"])
                tags = extra_details.get("tags", ["No Tags"])

                # Store event data
                event_data = {
                    "name": title,
                    "organization": organization,
                    "location": location,
                    "dates": dates,
                    "start_time": start_time,
                    "end_time": end_time,
                    "phone": phone,
                    "image_url": image_url,
                    "description": description,
                    "event_url": event_url,
                    "email": extra_details.get("email", "No Email"),
                    "price": extra_details.get("price", "No Price"),
                    "ages": ages,
                    "tags": tags,
                }
                all_events.append(event_data)

                # Store into Supabase
                supabase.table("activities").insert([event_data]).execute()

    return {
        "message": "Scraping completed!",
        "test_mode": TEST_MODE,
        "events": all_events,
    }


# ✅ **Initialize Selenium WebDriver**
def get_selenium_driver():
    options = webdriver.ChromeOptions()
    options.add_argument("--headless")  # Run in headless mode
    options.add_argument(f"user-agent={random.choice(USER_AGENTS)}")
    options.add_argument("--disable-blink-features=AutomationControlled")
    return webdriver.Chrome(
        service=Service(ChromeDriverManager().install()), options=options
    )


def scrape_activityhero_event_details(event_url):
    """Scrapes more details like full location, time, pricing from event page."""
    print(f"🔍 Scraping event details: {event_url}")
    driver = get_selenium_driver()
    driver.get(event_url)
    time.sleep(3)  # Allow JavaScript to load

    soup = BeautifulSoup(driver.page_source, "html.parser")

    # ✅ Extract Organizer
    organizer_element = soup.select_one("a.biz-title")
    organizer = organizer_element.text.strip() if organizer_element else "No Organizer"

    # ✅ Extract Full Location Address
    location_element = soup.select_one("div.activity-page-sessions-container")
    location = location_element.text.strip() if location_element else "No Location"

    # ✅ Extract Event Times
    time_element = soup.select_one("div.time-str.section")
    time_text = time_element.text.strip() if time_element else "No Time"
    start_time, end_time = extract_start_end_time(time_text)

    # ✅ Extract Date Range
    date_element = soup.select_one("div.section strong")
    event_dates = date_element.text.strip() if date_element else "No Date"

    # ✅ Extract Age Group
    age_element = soup.select_one(".age.container.clearfix")
    ages = [age_element.text.strip()] if age_element else ["No Age Info"]

    # ✅ Extract Tags
    tag_elements = soup.select(".activity-categories p")
    tags = [tag.text.strip() for tag in tag_elements] if tag_elements else ["No Tags"]

    # ✅ Extract Prices (Both Adult and Child Prices)
    price_elements = soup.select(".section")
    extracted_prices = re.findall(
        r"\d+\.\d+|\d+", " ".join([p.text for p in price_elements])
    )
    prices = [float(price) for price in extracted_prices] if extracted_prices else [0.0]

    # ✅ Extract Description
    description_element = soup.select_one(".activity-description")
    description = (
        description_element.text.strip() if description_element else "No Description"
    )

    driver.quit()

    return {
        "organizer": organizer,
        "location": location,
        "dates": event_dates,
        "start_time": start_time,
        "end_time": end_time,
        "ages": ages,
        "tags": tags,
        "price": prices[0],  # Stored as a list [Adult Price, Child Price]
        "description": description,
    }


# ✅ **Scrape event listings from ActivityHero main page**
def scrape_activityhero():
    """Scrapes event listings from ActivityHero and limits to 5 items for testing."""
    print(f"🔍 Scraping ActivityHero events from: {ACTIVITYHERO_URL}")

    driver = get_selenium_driver()
    driver.get(ACTIVITYHERO_URL)
    time.sleep(5)  # Wait for JavaScript to load

    soup = BeautifulSoup(driver.page_source, "html.parser")
    driver.quit()  # Close Selenium

    event_items = soup.select("div.tile-title.new-version > a")

    all_events = []
    max_events_to_scrape = 5  # ✅ Limit to 5 events
    scraped_count = 0

    if not event_items:
        print(f"❌ No event listings found on ActivityHero.")
        return {"message": "No events found on ActivityHero!", "events": []}
    print(event_items)
    return;
    for event in event_items:
        if scraped_count >= max_events_to_scrape:  # ✅ Stop after 5 events
            break

        # Extract Event Title
        title = event.text.strip()
        event_url = BASE_URL + event["href"] if event else None

        # Extract Image URL
        image_element = event.find_previous("img")
        image_url = image_element["src"] if image_element else "No Image"

        # Extract Date
        date_element = event.find_next("div", class_="date-item")
        event_date = date_element.text.strip() if date_element else "No Date"

        # Extract Location Summary
        location_element = event.find_next("div", class_="location")
        location_summary = (
            location_element.text.strip() if location_element else "No Location Info"
        )

        # ✅ Fetch details for the first 5 events only
        extra_details = (
            scrape_activityhero_event_details(event_url) if event_url else {}
        )

        # Store event data
        event_data = {
            "title": title,
            "organization": extra_details.get("organizer", "No Organizer"),
            "location": extra_details.get("location", location_summary),
            "dates": [event_date],
            "start_time": extra_details.get("start_time", "Unknown"),
            "end_time": extra_details.get("end_time", "Unknown"),
            "phone": "No Phone",
            "image_url": image_url,
            "description": extra_details.get("description", "No Description"),
            "event_url": event_url,
            "email": "No Email",
            "price": extra_details.get("price", 0.0),  # Always store as float
            "ages": extra_details.get("ages", ["No Ages"]),
            "tags": extra_details.get("tags", ["No Tags"]),
        }

        all_events.append(event_data)
        supabase.table("activities").insert([event_data]).execute()

        scraped_count += 1  # ✅ Increment after scraping each event

    return {"message": "Scraping completed for ActivityHero!", "events": all_events}


# ✅ **FastAPI route for ActivityHero scraper**
@app.get("/scrape-activityhero")
def scrape_activityhero_route():
    return scrape_activityhero()


def get_region_links():
    """Fetches all Galileo camp region links dynamically with improved handling."""
    print(f"🔍 Fetching region links from {GALILEO_BASE_URL}")

    driver = get_selenium_driver()
    driver.get(GALILEO_BASE_URL)

    try:
        # ✅ Scroll down to trigger JS-based content loading
        driver.execute_script("window.scrollBy(0, 800);")
        time.sleep(3)
        # ✅ Wait for the first region link to appear (Max wait: 10s)
        # WebDriverWait(driver, 10).until(
        #     EC.presence_of_element_located((By.CSS_SELECTOR, "footer-camps__location.ul.li"))
        # )
        # ✅ Extract the updated page source
        soup = BeautifulSoup(driver.page_source, "html.parser")
        footer_containers = soup.select(".footer-camps__location")
        region_links = {}
        index=0
        # Loop through each container and extract anchor tags
        for container in footer_containers[1:]:
            # Find all anchor tags (<a>) in the current container
            regions = container.find_all("a")
            button = container.find('button', class_='btn')
            button_text = button.get_text(strip=True)

            # Remove "Summer Camps" from the button text
            cleaned_button_text = button_text.replace("Summer Camps", "").strip()
            print(region_links)
            # Loop through all anchor tags
            for region in regions:
                # Get the region name (anchor text) and the href (URL)
                region_name = region.text.strip()  # Get the text inside the <a> tag (the region name)
                region_url = region.get("href", "").strip()  # Get the href attribute (the region URL)
        
                # If the region_url doesn't start with "http", convert it to an absolute URL
                if region_url and not region_url.startswith("http"):
                    region_url = GALILEO_BASE_URL + region_url  # Convert to absolute URL

                # Add the region name and URL to the dictionary
                if region_url:
                    region_links[index] = {"button_text": cleaned_button_text, "region_url": region_url}
                
                index += 1

        # soup = BeautifulSoup(driver.page_source, "html.parser")
        # print(soup)
        # region_links = {}
        # anchor_tags = soup.select(".footer-camps__container a")

        # Extract the href attribute (the link) from each anchor tag
        # links = [anchor.get('href') for anchor in anchor_tags if anchor.get('href')]
        # for link in links:
        #     print(link)
        # ✅ Fetch region links
        # for region in soup.select("a.locations_item"):
        #     region_name = region.select_one("img")[
        #         "alt"
        #     ].strip()  # Extract "Chicago" from `alt`
        #     region_url = region["href"].strip()
        #     if not region_url.startswith("http"):
        #         region_url = GALILEO_BASE_URL + region_url  # Convert to absolute URL

        #     region_links[region_name] = region_url

        print(f"✅ Found Regions: {list(region_links.keys())}")

    except Exception as e:
        print(f"❌ Error fetching regions: {str(e)}")
        region_links = {}

    finally:
        driver.quit()  # Always close Selenium instance

    return region_links


# ✅ **Step 2: Extract All Camp Information Links**
def get_all_camp_links(region_url):
    """Fetches all camps listed under a region."""
    print(f"🔍 Fetching camps from region: {region_url}")

    driver = get_selenium_driver()
    driver.get(region_url)
    time.sleep(5)  # Wait for JS to load

    soup = BeautifulSoup(driver.page_source, "html.parser")
    driver.quit()

    camp_links = []
    for camp in soup.select("a.location-card_link"):
        camp_url = camp["href"]
        if not camp_url.startswith("http"):
            camp_url = GALILEO_BASE_URL + camp_url
        camp_links.append(camp_url)

    print(f"✅ Found {len(camp_links)} camps in region!")
    return camp_links


# ✅ **Step 3: Scrape Individual Camp Details**
def scrape_galileo_camp_details(camp_url):
    """Scrapes details from individual camp pages."""
    print(f"🔍 Scraping camp details: {camp_url}")

    driver = get_selenium_driver()
    driver.get(camp_url)
    time.sleep(3)  # Allow JavaScript to load

    soup = BeautifulSoup(driver.page_source, "html.parser")
    driver.quit()

    # Camp Name
    title_element = soup.select_one("h1.heading-1")
    camp_name = title_element.text.strip() if title_element else "No Title"

    # Location
    location_element = soup.select_one("p.camp-main_school strong")
    location = location_element.text.strip() if location_element else "No Location"

    # Address
    address_element = soup.select_one("ul.camp-main_meta")
    address = address_element.text.strip() if address_element else "No Address"

    # Phone Number
    phone_element = soup.select_one("ul.camp-main_meta li span")
    phone = phone_element.text.strip() if phone_element else "No Phone Number"

    # Grades
    grade_element = soup.find("p", text=re.compile(r"Grades", re.I))
    grades = (
        grade_element.text.replace("Grades:", "").strip()
        if grade_element
        else "No Grade Info"
    )

    # Date Range
    date_element = soup.find("p", text=re.compile(r"Running from", re.I))
    date_range = (
        date_element.text.replace("Running from:", "").strip()
        if date_element
        else "No Date Info"
    )

    # Description
    description_element = soup.select_one("div.camp-main_content")
    description = (
        description_element.text.strip() if description_element else "No Description"
    )

    # Image URL
    image_element = soup.select_one("div.camp-main img")
    image_url = image_element["src"] if image_element else "No Image"

    print(
        f"✅ Scraped {camp_name} {location} {address} {phone} {grades} {date_range} {description} {image_url} {camp_url}"
    )

    return {
        "camp_name": camp_name,
        "location": location,
        "address": address,
        "phone": phone,
        "grades": grades,
        "dates": date_range,
        "description": description,
        "image_url": image_url,
        "camp_url": camp_url,
    }


# ✅ **Step 4: Scrape All Galileo Camps**
def scrape_galileo_camps():
    """Scrapes camps by region and stores them in Supabase."""
    regions = get_region_links()
    all_camps = []

    for region_name, region_url in regions.items():
        camp_links = get_all_camp_links(region_url)

        for camp_url in camp_links:
            camp_details = scrape_galileo_camp_details(camp_url)
            camp_details["region"] = region_name  # Add region name

            all_camps.append(camp_details)

            # Insert into Supabase
            supabase.table("camps").insert([camp_details]).execute()

    return {"message": "Scraping completed for Galileo Camps!", "camps": all_camps}
def grade_to_age_group(grade_range):
    # Mapping for age groups corresponding to grades
    grade_to_age = {
        "K": (5, 6),
        "1": (6, 7),
        "2": (7, 8),
        "3": (8, 9),
        "4": (9, 10),
        "5": (10, 11),
        "6": (11, 12),
        "7": (12, 13),
        "8": (13, 14),
        "9": (14, 15),
        "10": (16,17)
    }

    # Split the grade range
    start_grade, end_grade = grade_range.split(" - ")

    # If the grade range includes "K", handle it separately as "K" maps to a range of ages
    if start_grade == "K":
        start_age, _ = grade_to_age["K"]
    else:
        start_age = grade_to_age[start_grade][0]

    # If the end grade is "K", handle it separately
    if end_grade == "K":
        _, end_age = grade_to_age["K"]
    else:
        end_age = grade_to_age[end_grade][1]

    return f"{start_age} - {end_age}"

def get_address_details(address):
    # Use Nominatim API for reverse geocoding
    url = f"https://nominatim.openstreetmap.org/search?q={address}&format=json&addressdetails=1"
    
    # Send the request
    response = requests.get(url)
    data = response.json()
    
    if data:
        # Extract the first result
        result = data[0]
        
        # Get the necessary address components
        street = result.get("address", {}).get("road", "")
        city = result.get("address", {}).get("city", "")
        state = result.get("address", {}).get("state", "")
        postal_code = result.get("address", {}).get("postcode", "")
        country = result.get("address", {}).get("country", "")
        
        # Construct the final dictionary with Google Maps URL
        address_dict = {
            "street": street,
            "city": city,
            "state": state,
            "postal_code": postal_code,
            "country": country,
            "google_maps": f"https://www.openstreetmap.org/?mlat={result['lat']}&mlon={result['lon']}"
        }
        
        return address_dict

def scrape_galileo_camp_details2(camp_url,country):
    """Scrapes details from individual camp pages."""
    print(f"🔍 Scraping camp details: {camp_url}")
    driver = get_selenium_driver()
    driver.get(camp_url)
    time.sleep(3)  # Allow JavaScript to load
    soup = BeautifulSoup(driver.page_source, "html.parser")
    driver.quit()
    # Camp Name
    title_element = soup.select_one("h1.heading-1")
    camp_name = title_element.text.strip() if title_element else "No Title"

    
    # Location
    location_element = soup.select_one("p.camp-main_school strong")
    location = location_element.text.strip() if location_element else "No Location"
    address = "No Address"
    phone = "No Phone Number"
    list_items = soup.select("ul.camp-main__meta li")
    if len(list_items) > 0:
        address_element = list_items[0].get_text(strip=True)
        address = address_element if address_element else "No Address"

    # Check if list_items has at least two elements (Phone Number)
    if len(list_items) > 1:
        phone_element = list_items[1].get_text(strip=True)
        phone = phone_element if phone_element else "No Phone Number"

    # In case the address is missing but phone is present, make sure to handle this properly
    if len(list_items) == 1:
        phone_element = list_items[0].get_text(strip=True)
        phone = phone_element if phone_element else "No Phone Number"

    content_div = soup.find('div', class_='camp-main__content')

    # Extract the text content from <p> tags within the div
    paragraph = content_div.find('p').get_text(separator=" ", strip=True)

    # Split the extracted text into Grades and Running from
    grades_element = paragraph.split("Running from:")[0].replace("Grades:", "").strip()
    grades = grades_element if grades_element else "No Date Info"


    date_element = paragraph.split("Running from:")[1].strip()
    date_range = date_element if date_element else "No Date Info"

    # Description
    description_element = soup.find('p', class_='camp-main__school').find('strong')
    description = (
        description_element.text.strip() if description_element else "No Description"
    )

    # Image URL
    image_element = soup.select_one("div.camp-main img")
    image_url = image_element["src"] if image_element else "No Image"

    year = 2025

    # Map months from name to number
    month_map = {
        "January": "01",
        "February": "02",
        "March": "03",
        "April": "04",
        "May": "05",
        "June": "06",
        "July": "07",
        "August": "08",
        "September": "09",
        "October": "10",
        "November": "11",
        "December": "12",
    }

    # Split the date range into start and end
    start_date, end_date = date_range.split(" - ")

    # Parse the start and end month-day strings
    start_month, start_day = start_date.split(" ")
    end_month, end_day = end_date.split(" ")

    # Convert month names to numbers
    start_month_num = month_map[start_month]
    end_month_num = month_map[end_month]

    # Format the start date as MM/DD/YYYY
    start_date_formatted = f"{int(start_day):02d}/{start_month_num}/{year}"

    # Format the end date as MM/DD/YYYY
    end_date_formatted = f"{int(end_day):02d}/{end_month_num}/{year}"

    date_range_formatted = f"{start_date_formatted} - {end_date_formatted}"

    print(
        f"✅ Scraped {camp_name} {location} {address} {phone} {grades} {date_range} {description} {image_url} {camp_url}"
    )

    return {
            "name": camp_name,
            "organization": "No Organizer",
            "location": {"street":address,"country":country},
            "dates": [date_range_formatted],
            "start_time": "Unknown",
            "end_time": "Unknown",
            "phone": phone,
            "image_url": image_url,
            "description": description,
            "event_url": camp_url,
            "email": "No Email",
            "price":  0.0,
            "ages": [grade_to_age_group(grades)],
            "tags":  ["No Tags"],
    }
   

def scrape_galileo_camps2():
    """Scrapes camps by region and stores them in Supabase."""
    regions = get_region_links()
    print(regions)
    all_camps = []

    for index, region_data in regions.items():
        camp_details = scrape_galileo_camp_details2(region_data['region_url'],region_data['button_text'])
        all_camps.append(camp_details)
            # Insert into Supabase
        

    return {"message": "Scraping completed for Galileo Camps!", "camps": all_camps}



# ✅ **FastAPI Route**
@app.get("/scrape-galileo-camps")
def scrape_galileo_camps_route():
    return scrape_galileo_camps()



def scrape_Campity_camp():
    with open('data.js', 'r') as file:
        js_data = file.read()

    # You would use js2py or another method to parse the JS to JSON, here assuming it is already JSON formatted
    # For example, manually converting to a JSON array for simplicity:
    events = json.loads(js_data)  # You can replace this with actual parsing logic if necessary

    # Check structure of events (for debugging)
    print(events)
    ev = {}
    index=0
    # Insert data into Supabase
    for event in events:
        custom_event = {
            "name": event["name"],
            "organization": "Campitycamp",
            "location": {"lat":event["lat"],"lon":event["lon"]},
            "dates": event["availableWeeks"],
            "start_time": event["dropoff"],
            "end_time": event["pickup"],
            "phone": "No Phone",
            "image_url": f"https://www.campitycamp.com{event["img"]}",
            "description": event["description"],
            "event_url": event["booking_url"],
            "email": "No Email",
            "price":  event["cost"],
            "ages": [f"{event['ageFrom']} - {event['ageTo']} years"],
            "tags":  ["No Tags"],
        }
        supabase.table("activities").insert([custom_event]).execute()
    print(index)
    # print(ev)
    # Assuming you have a 'events' table with columns matching event data structure
    supabase.table('events').insert(event).execute()

# result = scrape_galileo_camps2()
# print(result)

def convert_date_format(date_text):
    # Handle range format: "Mar 22 - Apr 5, 2025 (Started Jan 18)"
    range_match = re.search(r"([A-Za-z]+ \d{1,2}) - ([A-Za-z]+ \d{1,2}), (\d{4})", date_text)
    if range_match:
        start_date = parser.parse(f"{range_match.group(1)} {range_match.group(3)}").strftime("%d/%m/%Y")
        end_date = parser.parse(f"{range_match.group(2)} {range_match.group(3)}").strftime("%d/%m/%Y")
        return f"{start_date} - {end_date}"
    
    # Handle single date format: "Sat, Apr 5, 2025"
    try:
        single_date = parser.parse(date_text).strftime("%d/%m/%Y")
        return single_date
    except:
        return "No Dates"

def scrape_activityhero_event_details2(event_url):
    """Scrapes more details like full location, time, pricing from event page."""
    print(f"🔍 Scraping event details: {event_url}")

    driver = get_selenium_driver()
    driver.get(event_url)
    time.sleep(6)  # Allow JavaScript to load
    soup = BeautifulSoup(driver.page_source, "html.parser")
    button = driver.find_element(By.ID, "check-sessions")

    button.click()

    time.sleep(3)
    modal = driver.find_element(By.CLASS_NAME, 'modal-content')  # Replace with the actual class name of your modal
    modal_html = modal.get_attribute('outerHTML')
    soup1 = BeautifulSoup(modal_html, "html.parser")
    # print(soup1)
    driver.quit()

    
    title_element = soup.select_one(".header-title")
    title = title_element.text.strip() if title_element else "No Title"
    # ✅ Extract Organizer
    organizer_element = soup.select_one(".provider-review-name")
    organizer = organizer_element.text.strip() if organizer_element else "No Organizer"

    name_element =  soup.select_one('.schedule-location-container')

    name = name_element.contents[0].strip()
    address = name_element.find('a').get_text() 

    #Phone element
    phone_element = soup.find('span', class_='phone-number') 
    phone = phone_element.text.strip() if phone_element else "No Phone"

    # ✅ Extract Event Times
    # time_element = soup.select_one("div.time-str.section")
    # time_text = time_element.text.strip() if time_element else "No Time"
    # start_time, end_time = extract_start_end_time(time_text)

    # ✅ Extract Age Group


    #img
    first_image_url = soup.find('div', class_='carousel-image-wrapper').find('img')['src']

    description_element = soup.find('div',class_='overview').find('p')
    description = (
        description_element.text.strip() if description_element else "No Description"
    )

    # ✅ Extract Prices (Both Adult and Child Prices)

    price_elements = soup1.find('div',class_='alt-price-wrapper')
    extracted_prices = re.findall(r'\d+\.\d+', price_elements.get_text(strip=True)) if price_elements else 0
    prices = (float(price) for price in extracted_prices) if extracted_prices else 0.0


    popover_div = soup1.select_one('.popover-container-class .section strong')
    date = [convert_date_format(popover_div.text.strip())]if popover_div else "No Date"


    time_element = soup1.find('div',class_="time-str")
    time_text = time_element.contents[0].strip()  if time_element else "No Time"
    start_time, end_time = extract_start_end_time(time_text)

    age_element = soup1.find('div',class_="age-str")
    ages = [age_element.get_text(strip=True)] if age_element else ["No Age Info"]

    # print(start_time)
    # print(end_time)


    return {
        "name": title,
        "organization": "Activityhero",
        "location": {"street":address},
        "dates": [date],
        "start_time":start_time,
        "end_time": end_time,
        "phone": phone,
        "image_url": first_image_url,
        "description": description,
        "event_url": event_url,
        "email": "No Email",
        "price":  prices,
        "ages": [ages],
        "tags":  ["No Tags"],
    }

def scrape_activityhero2():
    """Scrapes event listings from ActivityHero and limits to 5 items for testing."""
    print(f"🔍 Scraping ActivityHero events from: {ACTIVITYHERO_URL}")

    driver = get_selenium_driver()
    driver.get(ACTIVITYHERO_URL)
    time.sleep(5)  # Wait for JavaScript to load

    soup = BeautifulSoup(driver.page_source, "html.parser")
    driver.quit()  # Close Selenium

    event_items = soup.select("div.tile-title.new-version > a")

    all_events = []
    max_events_to_scrape = 5  # ✅ Limit to 5 events
    scraped_count = 0

    if not event_items:
        print(f"❌ No event listings found on ActivityHero.")
        return {"message": "No events found on ActivityHero!", "events": []}
    print(event_items)
    for event in event_items:
        if scraped_count >= max_events_to_scrape:  # ✅ Stop after 5 events
            break

        # Extract Event Title
        title = event.text.strip()
        event_url = BASE_URL + event["href"] if event else None

        # Extract Image URL
        image_element = event.find_previous("img")
        image_url = image_element["src"] if image_element else "No Image"

        # Extract Date
        date_element = event.find_next("div", class_="date-item")
        event_date = date_element.text.strip() if date_element else "No Date"

        # Extract Location Summary
        location_element = event.find_next("div", class_="location")
        location_summary = (
            location_element.text.strip() if location_element else "No Location Info"
        )

        # ✅ Fetch details for the first 5 events only
        extra_details = (
            scrape_activityhero_event_details2(event_url) if event_url else {}
        )

        # Store event data

        all_events.append(extra_details)
        supabase.table("activities").insert([extra_details]).execute()

        scraped_count += 1  # ✅ Increment after scraping each event

    return {"message": "Scraping completed for ActivityHero!", "events": all_events}

def convert_date(date_str):
    try:
        date = datetime.strptime(f"{date_str} {2025}", "%b %d %Y")  
        return date.strftime("%d/%m/%Y")  
    except ValueError:
        return None

# Function to extract start and end times
def extract_times(time_str):
    # Updated regex pattern to account for optional spaces and AM/PM in any case
    time_pattern = r"(\d{1,2}:\d{2}\s*[APap]{2})\s*-\s*(\d{1,2}:\d{2}\s*[APap]{2})"
    times = re.findall(time_pattern, time_str.strip())
    
    if len(times) == 1:
        # Return the start and end times from the match
        return times[0][0].strip().lower(), times[0][1].strip().lower()
    else:
        # Return "Unparsed" if times are not properly parsed
        return "Unparsed", "Unparsed"





@app.get("/scrape-activityhero2")
def scrape_activityhero_route2():
    return scrape_activityhero2()

# result = steveandkatescamp("https://steveandkatescamp.com/mar-vista/")
# print(result)


def get_all_camp_links_for_steve_kates():
    """Fetches all camps listed under a region."""
    print(f"🔍 Fetching camps from region: {'https://steveandkatescamp.com/locations/'}")

    driver = get_selenium_driver()
    driver.get("https://steveandkatescamp.com/locations/")
    time.sleep(5)  # Wait for JS to load

    soup = BeautifulSoup(driver.page_source, "html.parser")
    driver.quit()

    camp_links = []

    for details in soup.find_all("details"):
        summary = details.find("summary")
        if summary:
            country_name = summary.text.strip()
            for a in details.find_all("a", href=True):
                link_text = a.get_text(separator=" ", strip=True)  # Get text and remove <br>
                link_url = a["href"]  # Get href attribute
    
                camp_links.append([country_name, link_url, link_text])  # Store country, text, and link
    
                print(country_name)
                print(link_text)
                print(link_url)

    print(f"✅ Found {len(camp_links)} camps in region!")
    return camp_links

def steveandkatescamp(event_url,country_name, link_text):
    """Scrapes more details like full location, time, pricing from event page."""
    print(f"🔍 Scraping event details: {event_url}")

    driver = get_selenium_driver()
    driver.get(event_url)
    time.sleep(3)  # Allow JavaScript to load
    soup = BeautifulSoup(driver.page_source, "html.parser")
    
    scraped_data = {}
    for box in soup.find_all('div', class_='camp-details-info-box'):
        if not box.get_text(strip=True):
            continue 
        title = box.find('p', class_='camp-details-info-title').get_text(separator=' ', strip=True)
        content = box.find('p', class_='camp-details-info-content').get_text(separator=' ', strip=True)
    
        if title == "DATES":
            # Convert dates to dd/mm/yyyy-dd/mm/yyyy format
            date_range = content.split(" - ")
            if len(date_range) == 2:
                start_date = convert_date(date_range[0])
                end_date = convert_date(date_range[1])
                if start_date and end_date:
                    scraped_data['DATES'] = f"{start_date}-{end_date}"
                else:
                     "No Date"
    
        elif title == "HOURS":
            # Extract start and end times
            start_time, end_time = extract_start_end_time(content)
            print(content)
            if start_time and end_time:
                scraped_data['HOURS'] = {'start_time': start_time, 'end_time': end_time}
    
        elif title == "NOTES":
            scraped_data['NOTES'] = content
        elif title == "AGES":
            scraped_data['AGES'] = content
        elif title == "ADDRESS":
            scraped_data['ADDRESS'] = content
        elif title == "DIRECTOR":
            scraped_data['DIRECTOR'] = content
        elif title == "EMAIL":
            scraped_data['EMAIL'] = content
        elif title == "CALL/TEXT":
            scraped_data['CALL/TEXT'] = content
        elif title == "FOOD":
            scraped_data['FOOD'] = content


    return {
        "name": link_text,
        "organization": "Steve and Kates",
        "location": {"street":scraped_data.get('ADDRESS', "No Address"),"country":country_name},
        "dates": [scraped_data.get('DATES', "No Dates")],
        "start_time":scraped_data.get('HOURS', {}).get("start_time", "Unparsed Time"),
        "end_time": scraped_data.get('HOURS', {}).get("end_time", "Unparsed Time"),
        "phone": scraped_data.get('CALL/TEXT', "No Phone"),
        "description": "Coding. Sewing. Baking. Making. Sporting. Filming. Lounging. Every day, campers face the excruciating task of choosing from these and many more engrossing activities. Some select a mix of many. Others burrow deep into one or two. Either way, each day they face new experiences bristling with trade-offs and tantalizing possibilities.In the early morning and late afternoon, campers ramp up and wind down with recreational choices.",
        "event_url": event_url,
        "email": scraped_data.get('EMAIL', "No Email"),
        "price":  120.00,
        "ages": [scraped_data.get('AGES', "No Age")],
        "tags":  ["No Tags"],
    }

def scrape_stevekate_camps():
    """Scrapes camps by region and stores them in Supabase."""
    regions = get_all_camp_links_for_steve_kates()
    all_camps = []
    return
    for country_name, link , link_text in regions[21:]:
        camp_details = steveandkatescamp(link,country_name, link_text)
        if not camp_details:
            continue
        print(camp_details)
        all_camps.append(camp_details)

        # Insert into Supabase
        supabase.table("activities").insert([camp_details]).execute()

    return {"message": "Scraping completed for stevekate Camps!", "camps": all_camps}


