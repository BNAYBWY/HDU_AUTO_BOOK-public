import os
import time
import yaml
import queue
import random
import logging
import requests

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import wraps

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.wait import WebDriverWait

# =========================
# 基础配置
# =========================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s'
)

TARGET_HOUR = 21
TARGET_MINUTE = 7

TZ_CST = ZoneInfo("Asia/Shanghai")

# =========================
# 重试装饰器
# =========================

def retry(max_retry=3, delay=1):

    def decorator(func):

        @wraps(func)
        def wrapper(*args, **kwargs):

            for i in range(max_retry):

                try:
                    return func(*args, **kwargs)

                except Exception as e:

                    logging.warning(
                        f"{func.__name__} 失败 "
                        f"{i + 1}/{max_retry} : {e}"
                    )

                    if i != max_retry - 1:
                        time.sleep(delay)

            raise Exception(f"{func.__name__} 最终失败")

        return wrapper

    return decorator


# =========================
# 抢座类
# =========================

class SeatAutoBooker:

    def __init__(self, cfg):

        self.cfg = cfg

        self.username = os.environ["SCHOOL_ID"].strip()
        self.password = os.environ["PASSWORD"].strip()

        self.session = requests.Session()

        self.driver = self.init_driver()

        self.wait = WebDriverWait(self.driver, 10)

        self.user_data = None

        self.cookie = ""

        self.stop_flag = False

    # =========================
    # 浏览器初始化
    # =========================

    def init_driver(self):

        options = Options()

        options.add_argument("--headless=new")

        options.add_argument("--disable-blink-features=AutomationControlled")

        options.add_argument("--no-sandbox")

        options.add_argument("--disable-dev-shm-usage")

        options.add_argument("--disable-gpu")

        options.add_argument("--window-size=1920,1080")

        options.add_argument(
            "--user-agent=Mozilla/5.0 "
            "(Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        )

        driver = webdriver.Chrome(
            service=Service(self.get_driver_path()),
            options=options
        )

        driver.execute_script("""
            Object.defineProperty(
                navigator,
                'webdriver',
                {get: () => undefined}
            )
        """)

        return driver

    def get_driver_path(self):

        import shutil

        path = shutil.which("chromedriver")

        if path:
            return path

        return "/usr/bin/chromedriver"

    # =========================
    # 通用元素查找
    # =========================

    def find_element_safe(
            self,
            selectors,
            timeout=5
    ):

        end_time = time.time() + timeout

        while time.time() < end_time:

            for selector in selectors:

                try:

                    elements = self.driver.find_elements(*selector)

                    for elem in elements:

                        if (
                            elem.is_displayed()
                            and
                            elem.is_enabled()
                        ):
                            return elem

                except:
                    continue

            time.sleep(0.2)

        return None

    # =========================
    # 登录
    # =========================

    @retry(max_retry=3)
    def login(self):

        logging.info("开始登录")

        self.driver.get(
            "https://hdu.huitu.zhishulib.com/"
        )

        time.sleep(3)

        username_selectors = [
            (By.ID, "username"),
            (By.NAME, "username"),
            (By.CSS_SELECTOR, "input[type='text']")
        ]

        password_selectors = [
            (By.ID, "password"),
            (By.NAME, "password"),
            (By.CSS_SELECTOR, "input[type='password']")
        ]

        button_selectors = [
            (By.XPATH, "//button[@type='submit']"),
            (By.XPATH, "//input[@type='submit']")
        ]

        username_input = self.find_element_safe(
            username_selectors
        )

        password_input = self.find_element_safe(
            password_selectors
        )

        submit_btn = self.find_element_safe(
            button_selectors
        )

        if not username_input:
            raise Exception("找不到用户名输入框")

        if not password_input:
            raise Exception("找不到密码输入框")

        if not submit_btn:
            raise Exception("找不到登录按钮")

        username_input.clear()
        username_input.send_keys(self.username)

        password_input.clear()
        password_input.send_keys(self.password)

        submit_btn.click()

        time.sleep(5)

        self.sync_cookie()

        if not self.verify_login():
            raise Exception("登录失败")

        logging.info("登录成功")

    # =========================
    # Cookie同步
    # =========================

    def sync_cookie(self):

        cookies = self.driver.get_cookies()

        cookie_list = []

        for c in cookies:

            self.session.cookies.set(
                c['name'],
                c['value']
            )

            cookie_list.append(
                f"{c['name']}={c['value']}"
            )

        self.cookie = "; ".join(cookie_list)

    # =========================
    # 登录验证
    # =========================

    def verify_login(self):

        headers = self.cfg["headers"].copy()

        headers["Cookie"] = self.cookie

        resp = self.session.get(
            "https://hdu.huitu.zhishulib.com/"
            "Seat/Index/searchSeats?LAB_JSON=1",
            headers=headers
        )

        try:

            data = resp.json()

            if "DATA" in data:

                self.user_data = data["DATA"]

                if "uid" in self.user_data:
                    return True

        except:
            pass

        return False

    # =========================
    # 时间等待
    # =========================

    def wait_until_target(self):

        now = datetime.now(TZ_CST)

        target = now.replace(
            hour=TARGET_HOUR,
            minute=TARGET_MINUTE,
            second=0,
            microsecond=0
        )

        if now >= target:
            target += timedelta(days=1)

        logging.info(
            f"等待至北京时间: "
            f"{target.strftime('%Y-%m-%d %H:%M:%S')}"
        )

        while True:

            now = datetime.now(TZ_CST)

            remain = (
                target - now
            ).total_seconds()

            if remain <= 0:
                break

            if remain > 1:
                time.sleep(0.5)
            else:
                break

        # 最后1秒高精度等待

        while datetime.now(TZ_CST) < target:
            pass

        logging.info("开始抢座")

    # =========================
    # 预热连接
    # =========================

    def warmup_connection(self):

        logging.info("预热连接")

        try:

            self.session.get(
                "https://hdu.huitu.zhishulib.com/",
                timeout=5
            )

        except:
            pass

    # =========================
    # 抢座
    # =========================

    def build_booking_data(
            self,
            seat_id,
            start_hour,
            duration_hour
    ):

        now = datetime.now(TZ_CST)

        book_time = now.replace(
            hour=start_hour,
            minute=0,
            second=0,
            microsecond=0
        )

        if now.hour >= TARGET_HOUR:
            book_time += timedelta(days=1)

        utc_time = book_time.astimezone(
            ZoneInfo("UTC")
        )

        timestamp = int(
            utc_time.timestamp()
        )

        return (
            f"beginTime={timestamp}"
            f"&duration={duration_hour * 3600}"
            f"&seats[0]={seat_id}"
            f"&seatBookers[0]={self.user_data['uid']}"
        )

    # =========================
    # 单线程抢座
    # =========================

    def book_single_seat(
            self,
            seat_id,
            start_hour,
            duration_hour
    ):

        if self.stop_flag:
            return False

        headers = self.cfg["headers"].copy()

        headers["Cookie"] = self.cookie

        data = self.build_booking_data(
            seat_id,
            start_hour,
            duration_hour
        )

        for _ in range(20):

            if self.stop_flag:
                return False

            try:

                resp = self.session.post(
                    self.cfg["target"],
                    data=data,
                    headers=headers,
                    timeout=3
                )

                result = resp.json()

                logging.info(
                    f"{seat_id} -> {result}"
                )

                if result.get("CODE") == "ok":

                    self.stop_flag = True

                    logging.info(
                        f"抢座成功: {seat_id}"
                    )

                    return True

            except Exception as e:

                logging.warning(
                    f"{seat_id} 抢座异常: {e}"
                )

        return False

    # =========================
    # 并发抢座
    # =========================

    def concurrent_booking(
            self,
            seat_list,
            start_hour,
            duration_hour
    ):

        with ThreadPoolExecutor(
                max_workers=len(seat_list)
        ) as executor:

            futures = []

            for seat in seat_list:

                futures.append(
                    executor.submit(
                        self.book_single_seat,
                        seat,
                        start_hour,
                        duration_hour
                    )
                )

            for future in as_completed(futures):

                result = future.result()

                if result:
                    return True

        return False

    # =========================
    # Server酱通知
    # =========================

    def notify(self, title, content):

        sckey = os.environ.get("SCKEY")

        if not sckey:
            return

        try:

            requests.post(
                f"https://sctapi.ftqq.com/{sckey}.send",
                data={
                    "title": title,
                    "desp": content
                },
                timeout=5
            )

        except Exception as e:

            logging.warning(
                f"通知失败: {e}"
            )

    # =========================
    # 退出
    # =========================

    def quit(self):

        try:
            self.driver.quit()
        except:
            pass


# =========================
# 主程序
# =========================

if __name__ == "__main__":

    logging.info("程序启动")

    with open(
            "user_config.yml",
            "r",
            encoding="utf-8"
    ) as f:

        user_config = yaml.safe_load(f)

    with open(
            "config/basic_config.yml",
            "r",
            encoding="utf-8"
    ) as f:

        basic_config = yaml.safe_load(f)

    s = SeatAutoBooker(
        basic_config["SeatAutoBooker"]
    )

    try:

        s.login()

        s.warmup_connection()

        s.wait_until_target()

        seat_list = user_config["自定义"]

        success = s.concurrent_booking(
            seat_list=seat_list,
            start_hour=9,
            duration_hour=13
        )

        if success:

            logging.info("抢座成功")

            s.notify(
                "HDU抢座成功",
                "已经成功抢到座位"
            )

        else:

            logging.error("抢座失败")

            s.notify(
                "HDU抢座失败",
                "所有座位均抢座失败"
            )

    except Exception as e:

        logging.error(f"程序异常: {e}")

        s.notify(
            "HDU抢座异常",
            str(e)
        )

    finally:

        s.quit()
