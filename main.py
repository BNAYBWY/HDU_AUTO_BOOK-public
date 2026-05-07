import os
import time
import yaml
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

TARGET_HOUR = 20
TARGET_MINUTE = 0

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
# 增强的输入框查找器
# =========================

class EnhancedInputFinder:
    """增强的输入框查找器，支持多种策略"""
    
    # 扩展的选择器列表
    USERNAME_SELECTORS = [
        (By.ID, "username"),
        (By.ID, "userName"),
        (By.ID, "user_name"),
        (By.ID, "loginName"),
        (By.ID, "loginname"),
        (By.NAME, "username"),
        (By.NAME, "userName"),
        (By.NAME, "user_name"),
        (By.NAME, "loginName"),
        (By.CLASS_NAME, "username"),
        (By.CLASS_NAME, "userName"),
        (By.CSS_SELECTOR, "input[type='text'][name*='user']"),
        (By.CSS_SELECTOR, "input[type='text'][name*='login']"),
        (By.CSS_SELECTOR, "input[placeholder*='用户名']"),
        (By.CSS_SELECTOR, "input[placeholder*='账号']"),
        (By.CSS_SELECTOR, "input[placeholder*='学号']"),
        (By.CSS_SELECTOR, "input[placeholder*='工号']"),
        (By.XPATH, "//input[@type='text' and contains(@placeholder, '用户名')]"),
        (By.XPATH, "//input[@type='text' and contains(@placeholder, '账号')]"),
        (By.XPATH, "//input[@type='text' and contains(@placeholder, '学号')]"),
        (By.XPATH, "//label[contains(text(), '用户名')]/following::input[1]"),
        (By.XPATH, "//label[contains(text(), '账号')]/following::input[1]"),
        (By.XPATH, "//label[contains(text(), '学号')]/following::input[1]"),
    ]
    
    PASSWORD_SELECTORS = [
        (By.ID, "password"),
        (By.ID, "pwd"),
        (By.ID, "passWord"),
        (By.NAME, "password"),
        (By.NAME, "pwd"),
        (By.CLASS_NAME, "password"),
        (By.CSS_SELECTOR, "input[type='password']"),
        (By.CSS_SELECTOR, "input[placeholder*='密码']"),
        (By.XPATH, "//input[@type='password' and contains(@placeholder, '密码')]"),
        (By.XPATH, "//label[contains(text(), '密码')]/following::input[1]"),
    ]
    
    SUBMIT_SELECTORS = [
        (By.XPATH, "//button[@type='submit']"),
        (By.XPATH, "//input[@type='submit']"),
        (By.XPATH, "//button[contains(text(), '登录')]"),
        (By.XPATH, "//button[contains(text(), '登陆')]"),
        (By.XPATH, "//input[@value='登录']"),
        (By.XPATH, "//input[@value='登陆']"),
        (By.CSS_SELECTOR, "button[class*='login']"),
        (By.CSS_SELECTOR, "button[class*='submit']"),
        (By.CLASS_NAME, "login-btn"),
        (By.CLASS_NAME, "submit-btn"),
    ]
    
    @classmethod
    def smart_find_input(cls, driver, selectors, timeout=10, description="输入框"):
        """智能查找输入框，支持iframe切换"""
        
        # 先在主页面查找
        for selector in selectors:
            try:
                elements = driver.find_elements(*selector)
                for elem in elements:
                    if elem.is_displayed() and elem.is_enabled():
                        logging.info(f"找到{description}: {selector}")
                        return elem
            except:
                continue
        
        # 查找iframe并切换进去
        frames = driver.find_elements(By.TAG_NAME, "iframe")
        frames.extend(driver.find_elements(By.TAG_NAME, "frame"))
        
        for i, frame in enumerate(frames):
            try:
                driver.switch_to.frame(frame)
                
                for selector in selectors:
                    try:
                        elements = driver.find_elements(*selector)
                        for elem in elements:
                            if elem.is_displayed() and elem.is_enabled():
                                logging.info(f"在iframe {i}中找到{description}: {selector}")
                                driver.switch_to.default_content()
                                return elem
                    except:
                        continue
                
                driver.switch_to.default_content()
            except:
                driver.switch_to.default_content()
                continue
        
        raise Exception(f"无法找到{description}")
    
    @classmethod
    def find_username_input(cls, driver, timeout=10):
        return cls.smart_find_input(driver, cls.USERNAME_SELECTORS, timeout, "用户名输入框")
    
    @classmethod
    def find_password_input(cls, driver, timeout=10):
        return cls.smart_find_input(driver, cls.PASSWORD_SELECTORS, timeout, "密码输入框")
    
    @classmethod
    def find_submit_button(cls, driver, timeout=10):
        return cls.smart_find_input(driver, cls.SUBMIT_SELECTORS, timeout, "登录按钮")


# =========================
# 倒计时显示器
# =========================

class CountdownDisplay:
    """倒计时显示器"""
    
    def __init__(self, target_time):
        self.target_time = target_time
        self.last_display = ""
        
    def update(self):
        """更新并返回倒计时字符串"""
        now = datetime.now(TZ_CST)
        
        if now >= self.target_time:
            return "倒计时: 00:00:00 - 开始抢座!"
        
        diff = self.target_time - now
        hours = diff.seconds // 3600
        minutes = (diff.seconds % 3600) // 60
        seconds = diff.seconds % 60
        
        countdown_str = f"倒计时: {hours:02d}:{minutes:02d}:{seconds:02d}"
        
        # 只在变化时打印，减少输出
        if countdown_str != self.last_display:
            # 使用 \r 实现同一行刷新
            print(f"\r{countdown_str}", end='', flush=True)
            self.last_display = countdown_str
        
        return countdown_str
    
    def display_until_target(self):
        """持续显示倒计时直到目标时间"""
        print("\n" + "="*50)
        print(f"目标时间: {self.target_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print("="*50)
        
        while True:
            countdown = self.update()
            
            if datetime.now(TZ_CST) >= self.target_time:
                print("\n" + "="*50)
                print("🎯 目标时间已到！开始抢座...")
                print("="*50 + "\n")
                break
            
            # 根据剩余时间调整刷新频率
            diff = self.target_time - datetime.now(TZ_CST)
            if diff.total_seconds() > 60:
                time.sleep(0.5)
            elif diff.total_seconds() > 10:
                time.sleep(0.2)
            else:
                time.sleep(0.05)


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
    # 增强的登录方法
    # =========================

    @retry(max_retry=3)
    def login(self):

        logging.info("开始登录")

        self.driver.get(
            "https://hdu.huitu.zhishulib.com/"
        )

        time.sleep(3)

        # 使用增强的输入框查找器
        username_input = EnhancedInputFinder.find_username_input(
            self.driver, timeout=10
        )

        password_input = EnhancedInputFinder.find_password_input(
            self.driver, timeout=10
        )

        submit_btn = EnhancedInputFinder.find_submit_button(
            self.driver, timeout=10
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
    # 时间等待（带倒计时显示）
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
            target += timedelta(days=2)

        logging.info(
            f"等待至北京时间: "
            f"{target.strftime('%Y-%m-%d %H:%M:%S')}"
        )
        
        # 创建并启动倒计时显示器
        countdown = CountdownDisplay(target)
        
        # 持续显示倒计时
        countdown.display_until_target()
        
        # 最后微调确保精确
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
