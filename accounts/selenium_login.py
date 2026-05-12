"""
AdvancedMD Selenium Login — Login to Dashboard
Only contains: setup_driver, perform_login, handle_popups, switch_to_dashboard_window
Long process (patient info, insurance, etc.) is in selenium_tasks.py (Celery)
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


def setup_driver(download_dir=None):
    options = Options()

    # Uncomment below line for headless/server mode
    # options.add_argument("--headless=new")

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


def run_login_to_dashboard(username, password, office_key):
    """
    Full login flow: setup driver → login → handle popups → confirm dashboard.
    Returns: (success: bool, error_message: str)
    """
    driver = None
    try:
        driver = setup_driver()

        if not perform_login(driver, username, password, office_key):
            return False, "Login failed — invalid credentials or page error."

        handle_popups(driver)

        if not switch_to_dashboard_window(driver):
            return False, "Dashboard did not load after login."

        return True, ""

    except Exception as e:
        return False, str(e)

    finally:
        if driver:
            try:
                driver.quit()
            except:
                pass


# ---------------------------------------------------------------------------
# End of Day Wizard
# ---------------------------------------------------------------------------

def click_eod_wizard(driver):
    """Click the End of Day Wizard icon in the AdvancedMD PM toolbar."""
    print("Waiting for dashboard toolbar to fully load...")

    # Wait for Angular toolbar to render
    try:
        WebDriverWait(driver, 30).until(
            EC.presence_of_element_located((By.CLASS_NAME, "pm-main-toolbar"))
        )
    except:
        pass
    time.sleep(4)  # Angular ng-repeat takes time to render icons

    print("Clicking End of Day Wizard icon...")
    selectors = [
        (By.ID, "mnuEodWizard"),
        (By.XPATH, "//*[@id='mnuEodWizard']"),
        (By.XPATH, "//i[@title='End of Day Wizard']"),
        (By.CSS_SELECTOR, "i.amds-eod-wizard"),
        (By.CSS_SELECTOR, ".amdicons.amds-eod-wizard"),
    ]

    end_time = time.time() + 30
    while time.time() < end_time:
        driver.switch_to.default_content()

        for by, val in selectors:
            try:
                elem = WebDriverWait(driver, 3).until(
                    EC.presence_of_element_located((by, val))
                )
                driver.execute_script("arguments[0].scrollIntoView(true);", elem)
                driver.execute_script("arguments[0].click();", elem)
                print("   Clicked EOD Wizard icon.")
                time.sleep(3)
                return True
            except:
                pass

        # Try inside iframes
        iframes = driver.find_elements(By.TAG_NAME, "iframe")
        for frame in iframes:
            try:
                driver.switch_to.default_content()
                driver.switch_to.frame(frame)
                for by, val in selectors:
                    try:
                        elem = driver.find_element(by, val)
                        if elem.is_displayed():
                            driver.execute_script("arguments[0].click();", elem)
                            print("   Clicked EOD Wizard icon (in iframe).")
                            time.sleep(3)
                            return True
                    except:
                        pass
            except:
                pass

        print("   EOD icon not found yet, retrying...")
        time.sleep(2)

    print("   Failed: EOD Wizard icon not found.")
    return False


def switch_to_eod_wizard_window(driver, handles_before):
    """Wait for the EOD Wizard popup window and switch to it."""
    print("Waiting for EOD Wizard window...")
    end_time = time.time() + 20

    while time.time() < end_time:
        new_handles = set(driver.window_handles) - handles_before
        if new_handles:
            driver.switch_to.window(new_handles.pop())
            # Wait for checklist table to appear
            try:
                WebDriverWait(driver, 15).until(
                    EC.presence_of_element_located((By.ID, "tblChecklist"))
                )
            except:
                pass
            print(f"   Switched to EOD Wizard window: {driver.title}")
            return True
        time.sleep(1)

    print("   Failed: EOD Wizard window did not open.")
    return False


def eod_handle_day_sheet_final(driver, wizard_handle, handles_before_run):
    """
    Special handler for 'Day Sheet - Final' step:
    1. A Report Center window opens — switch to it
    2. Click 'Run Report' button
    3. Handle 'Unapproved Charges exist!' dialog → click Yes
    4. Handle 'Day Close - Open Batches' dialog → click 'Close Batches & Continue'
    5. Wait 6 seconds for report to generate
    6. Close the Report Center window and return to wizard
    """
    print("      Day Sheet - Final: switching to Report Center window...")

    # Wait for the new Report Center window
    end_time = time.time() + 20
    report_handle = None
    while time.time() < end_time:
        new_handles = set(driver.window_handles) - handles_before_run
        if new_handles:
            report_handle = new_handles.pop()
            break
        time.sleep(1)

    if not report_handle:
        print("      Day Sheet - Final: Report Center window did not open.")
        return False

    driver.switch_to.window(report_handle)
    print(f"      Switched to Report Center: {driver.title}")
    time.sleep(3)

    # Click 'Run Report' button
    try:
        run_report_btn = WebDriverWait(driver, 15).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "button.run-report"))
        )
        driver.execute_script("arguments[0].click();", run_report_btn)
        print("      Clicked 'Run Report'.")
        time.sleep(2)
    except Exception as e:
        print(f"      Failed to click Run Report: {e}")
        driver.close()
        driver.switch_to.window(wizard_handle)
        return False

    # Handle 'Unapproved Charges exist!' → click Yes
    try:
        yes_btn = WebDriverWait(driver, 8).until(
            EC.element_to_be_clickable(
                (By.XPATH, "//button[normalize-space()='Yes'] | //input[@value='Yes']")
            )
        )
        driver.execute_script("arguments[0].click();", yes_btn)
        print("      Clicked 'Yes' on Unapproved Charges dialog.")
        time.sleep(2)
    except:
        print("      No 'Unapproved Charges' dialog appeared — continuing.")

    # Handle 'Day Close - Open Batches' → click 'Close Batches & Continue'
    try:
        close_batches_btn = WebDriverWait(driver, 8).until(
            EC.element_to_be_clickable(
                (By.XPATH, "//button[contains(normalize-space(), 'Close Batches')]"
                           " | //input[contains(@value, 'Close Batches')]")
            )
        )
        driver.execute_script("arguments[0].click();", close_batches_btn)
        print("      Clicked 'Close Batches & Continue'.")
    except:
        print("      No 'Day Close - Open Batches' dialog appeared — continuing.")

    # Wait for report to generate
    print("      Waiting 6 seconds for report to generate...")
    time.sleep(6)

    # Close Report Center window and return to wizard
    driver.close()
    driver.switch_to.window(wizard_handle)
    print("      Closed Report Center. Returned to EOD Wizard.")
    time.sleep(1)
    return True


def eod_click_step_and_run(driver, step_id, step_name):
    """
    In the EOD Wizard popup:
    1. Click the checklist row (step_id e.g. 'step1')
    2. Click the Run button
    3. If a new window opens (report), close it and come back
    Special case: step4 (Day Sheet - Final) has extra dialogs handled separately.
    """
    print(f"   Processing: {step_name} ({step_id})...")
    wizard_handle = driver.current_window_handle

    # Click the step row
    try:
        row = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, step_id))
        )
        driver.execute_script("arguments[0].click();", row)
        print(f"      Clicked row: {step_name}")
        time.sleep(1)
    except Exception as e:
        print(f"      Failed to click row {step_id}: {e}")
        return False

    # Click Run button
    handles_before_run = set(driver.window_handles)
    try:
        run_btn = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.ID, "btnRun"))
        )
        driver.execute_script("arguments[0].click();", run_btn)
        print(f"      Clicked Run for: {step_name}")
        time.sleep(3)
    except Exception as e:
        print(f"      Failed to click Run: {e}")
        return False

    # Step4 (Day Sheet - Final) has special Report Center flow
    if step_id == "step4":
        return eod_handle_day_sheet_final(driver, wizard_handle, handles_before_run)

    # All other steps: if a report window opened, close it and return to wizard
    new_handles = set(driver.window_handles) - handles_before_run
    if new_handles:
        report_handle = new_handles.pop()
        driver.switch_to.window(report_handle)
        print(f"      Report window opened: {driver.title} — closing...")
        time.sleep(2)
        driver.close()
        driver.switch_to.window(wizard_handle)
        print(f"      Returned to EOD Wizard.")
        time.sleep(1)

    return True


def run_eod_wizard(driver):
    """
    Full EOD Wizard flow — all 6 steps:
    1. Deposit Slip → Run → close report window
    2. Claims Center - Charge Review → Run → close
    3. Day Sheet - Trial → Run → close
    4. Day Sheet - Final → Run → close
    5. Claim Submission Wizard → Run → close
    6. Claims Center - Unbilled → Run → close → click Finish
    Returns: (success: bool, error_message: str)
    """
    handles_before = set(driver.window_handles)

    if not click_eod_wizard(driver):
        return False, "EOD Wizard icon not found on dashboard."

    if not switch_to_eod_wizard_window(driver, handles_before):
        return False, "EOD Wizard window did not open."

    steps = [
        ("step1", "Deposit Slip"),
        ("step2", "Claims Center - Charge Review"),
        ("step3", "Day Sheet - Trial"),
        ("step4", "Day Sheet - Final"),
        ("step5", "Claim Submission Wizard"),
        ("step6", "Claims Center - Unbilled"),
    ]

    for step_id, step_name in steps:
        if not eod_click_step_and_run(driver, step_id, step_name):
            return False, f"Failed at step: {step_name}"
        time.sleep(2)

    # Click Finish button after last step
    print("Clicking Finish button...")
    try:
        finish_btn = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.ID, "btnNext"))
        )
        driver.execute_script("arguments[0].click();", finish_btn)
        print("   EOD Wizard Finished successfully.")
        time.sleep(2)
    except Exception as e:
        print(f"   Warning: Could not click Finish button: {e}")

    print("EOD Wizard all steps completed successfully.")
    return True, ""

