"""
Shared AdvancedMD browser/login helpers.
Used by the End of Day Wizard (selenium_login.py) and the chart downloader (chart_download.py).
"""

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
import time
import os


def setup_driver(download_dir=None, extra_prefs=None, headless=False, maximized=False,
                 user_data_dir=None):
    options = Options()

    if user_data_dir:  # own Chrome profile, so parallel runs never share one
        os.makedirs(user_data_dir, exist_ok=True)
        options.add_argument(f"--user-data-dir={user_data_dir}")

    if headless:
        options.add_argument("--headless=new")

    if maximized and not headless:
        options.add_argument("--start-maximized")   # sized once, at launch - never resized later
    else:
        options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-popup-blocking")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )

    if download_dir:
        os.makedirs(download_dir, exist_ok=True)
        prefs = {
            "download.default_directory": download_dir,
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
            "safebrowsing.enabled": True,
        }
        if extra_prefs:
            prefs.update(extra_prefs)
        options.add_experimental_option("prefs", prefs)

    driver = webdriver.Chrome(options=options)
    return driver


def perform_login(driver, username, password, office_key):
    try:
        print(f"Opening login page...")
        driver.get("https://login.advancedmd.com/")
        wait = WebDriverWait(driver, 30)

        try:
            cookie_btn = WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.XPATH, "//button[contains(., 'Accept')]"))
            )
            cookie_btn.click()
        except:
            pass

        print("Switching to login iframe...")
        wait.until(EC.frame_to_be_available_and_switch_to_it((By.CSS_SELECTOR, "iframe")))

        wait.until(EC.element_to_be_clickable((By.ID, "loginName"))).send_keys(username)
        wait.until(EC.element_to_be_clickable((By.ID, "password"))).send_keys(password)
        office_field = wait.until(EC.element_to_be_clickable((By.ID, "officeKey")))
        office_field.clear()
        office_field.send_keys(office_key)
        office_field.send_keys("\t")

        print("Clicking login button...")
        wait.until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "button[type='submit']:not([disabled])"))
        ).click()
        print("Login submitted successfully.")

        driver.switch_to.default_content()
        return True
    except Exception as e:
        print(f"Login Error: {str(e)}")
        return False


def handle_popups(driver):
    print("Scanning for Login Popups...")
    end_time = time.time() + 30
    target_texts = ["Confirm later", "Snooze all", "Snooze", "Dismiss", "Ask me later", "Ask Me Later"]

    while time.time() < end_time:
        clicked_something = False

        def attempt_click():
            for text in target_texts:
                try:
                    xpath = (
                        f"//button[contains(normalize-space(.), '{text}')] | "
                        f"//a[contains(normalize-space(.), '{text}')] | "
                        f"//span[contains(normalize-space(.), '{text}')]"
                    )
                    elements = driver.find_elements(By.XPATH, xpath)
                    for elem in elements:
                        if elem.is_displayed() and elem.is_enabled():
                            try:
                                elem.click()
                            except:
                                try:
                                    ActionChains(driver).move_to_element(elem).click().perform()
                                except:
                                    try:
                                        elem.send_keys(Keys.RETURN)
                                    except:
                                        driver.execute_script("arguments[0].click();", elem)
                            return True
                except:
                    pass
            return False

        driver.switch_to.default_content()
        if attempt_click():
            clicked_something = True
        else:
            iframes = driver.find_elements(By.TAG_NAME, "iframe")
            for frame in iframes:
                try:
                    driver.switch_to.frame(frame)
                    if attempt_click():
                        clicked_something = True
                        driver.switch_to.default_content()
                        break
                    driver.switch_to.default_content()
                except:
                    driver.switch_to.default_content()

        if clicked_something:
            time.sleep(6)
        else:
            time.sleep(2)

        try:
            driver.switch_to.default_content()
            if (
                driver.find_elements(By.CLASS_NAME, "pm-main-toolbar")
                or driver.find_elements(By.ID, "mnuPatientInfo")
            ):
                print("Dashboard detected, moving forward!")
                break
        except:
            pass

    return True


def switch_to_dashboard_window(driver):
    print("Checking for Dashboard Window...")
    end_time = time.time() + 45

    while time.time() < end_time:
        handles = driver.window_handles

        if len(handles) > 1:
            driver.switch_to.window(handles[-1])
            print(f"Switched to new window: {driver.title}")
            return True

        try:
            if (
                driver.find_elements(By.CLASS_NAME, "pm-main-toolbar")
                or driver.find_elements(By.ID, "mnuPatientInfo")
            ):
                print("Dashboard loaded in the current main window.")
                return True
        except:
            pass

        time.sleep(2)

    print("Failed: Dashboard did not load.")
    try:
        screenshot_name = f"error_dashboard_{int(time.time())}.png"
        driver.save_screenshot(screenshot_name)
        print(f"Screenshot saved: {screenshot_name}")
    except Exception as e:
        print(f"Screenshot error: {e}")

    return False
