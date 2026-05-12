from celery import shared_task
from accounts.selenium_login import run_login_to_dashboard, run_eod_wizard
from accounts.selenium_login import setup_driver, perform_login, handle_popups, switch_to_dashboard_window


@shared_task(bind=True, max_retries=0)
def task_run_login(self, login_session_id):
    """
    Celery task: Run AdvancedMD login to dashboard.
    Updates LoginSession status to SUCCESS or FAILED.
    """
    from accounts.models import LoginSession

    session = LoginSession.objects.get(pk=login_session_id)
    session.status = LoginSession.STATUS_RUNNING
    session.save(update_fields=['status', 'updated_at'])

    try:
        success, error_msg = run_login_to_dashboard(
            session.username,
            session.password,
            session.office_key,
        )
        session.status = LoginSession.STATUS_SUCCESS if success else LoginSession.STATUS_FAILED
        session.error_message = error_msg
        session.save(update_fields=['status', 'error_message', 'updated_at'])

    except Exception as exc:
        session.status = LoginSession.STATUS_FAILED
        session.error_message = str(exc)
        session.save(update_fields=['status', 'error_message', 'updated_at'])
        raise


@shared_task(bind=True, max_retries=0)
def task_run_eod_wizard(self, login_session_id):
    """
    Celery task: Login to AdvancedMD → run EOD Wizard (step1 + step2).
    Updates LoginSession status to SUCCESS or FAILED.
    """
    from accounts.models import LoginSession

    session = LoginSession.objects.get(pk=login_session_id)
    session.status = LoginSession.STATUS_RUNNING
    session.save(update_fields=['status', 'updated_at'])

    driver = None
    try:
        driver = setup_driver()

        if not perform_login(driver, session.username, session.password, session.office_key):
            raise Exception("Login failed — invalid credentials or page error.")

        handle_popups(driver)

        if not switch_to_dashboard_window(driver):
            raise Exception("Dashboard did not load after login.")

        success, error_msg = run_eod_wizard(driver)

        session.status = LoginSession.STATUS_SUCCESS if success else LoginSession.STATUS_FAILED
        session.error_message = error_msg
        session.save(update_fields=['status', 'error_message', 'updated_at'])

    except Exception as exc:
        session.status = LoginSession.STATUS_FAILED
        session.error_message = str(exc)
        session.save(update_fields=['status', 'error_message', 'updated_at'])
        raise

    finally:
        if driver:
            try:
                driver.quit()
            except:
                pass
