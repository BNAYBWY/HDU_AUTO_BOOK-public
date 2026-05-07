import requests
import yaml
from datetime import datetime, timedelta
import json
import os
import logging
import time
import random
from functools import wraps

# 引入时区处理库
from zoneinfo import ZoneInfo

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.wait import WebDriverWait
from selenium.common.exceptions import TimeoutException, NoSuchElementException, ElementNotInteractableException

# --- 基本配置 ---
logging.basicConfig(
    format='%(asctime)s,%(msecs)d %(name)s %(levelname)s %(message)s',
    datefmt='%H:%M:%S',
    level=logging.INFO)

# --- 定义抢座目标时间 (东八区时间) ---
TARGET_HOUR = 20
TARGET_MINUTE = 00

def retry_on_failure(max_retries=3, delay=1, backoff=2):
    """重试装饰器"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            retries = 0
            current_delay = delay
            
            while retries < max_retries:
                try:
                    result = func(*args, **kwargs)
                    if result is not None and result != -1:
                        return result
                except Exception as e:
                    logging.warning(f"函数 {func.__name__} 执行失败 (尝试 {retries + 1}/{max_retries}): {e}")
                
                retries += 1
                if retries < max_retries:
                    # 添加随机延迟避免反爬
                    time.sleep(current_delay + random.uniform(0, 0.5))
                    current_delay *= backoff
            
            logging.error(f"函数 {func.__name__} 在 {max_retries} 次尝试后仍然失败")
            return -1
        return wrapper
    return decorator

class SeatAutoBooker:
    def __init__(self, booker_config):
        self.user_data = None
        logging.info('Creating SeatAutoBooker object')

        self.un = os.environ["SCHOOL_ID"].strip()
        self.pd = os.environ["PASSWORD"].strip()
        self.SCKey = os.environ.get("SCKEY", "")
        print(f"使用用户：{self.un}")

        if not self.SCKey:
            print("没有Server酱的key,将不会推送消息")

        chrome_options = Options()
        chrome_options.add_argument('--headless')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--disable-gpu')
        chrome_options.add_argument('--window-size=1920,1080')
        # GitHub Actions环境优化
        chrome_options.add_argument('--disable-web-security')
        chrome_options.add_argument('--disable-features=VizDisplayCompositor')
        chrome_options.add_argument('--disable-blink-features=AutomationControlled')
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
        chrome_options.add_experimental_option('useAutomationExtension', False)
        
        # 尝试多个可能的chromedriver路径
        chromedriver_path = self.get_chromedriver_path()
        logging.info(f"使用ChromeDriver: {chromedriver_path}")
        
        self.driver = webdriver.Chrome(service=Service(chromedriver_path), options=chrome_options)
        self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        self.driver.set_page_load_timeout(30)
        self.wait = WebDriverWait(self.driver, 20, 0.5)
        self.cookie = None
        self.cfg = booker_config

    def get_chromedriver_path(self):
        """获取chromedriver路径"""
        import shutil
        
        # 检查PATH中的chromedriver
        path = shutil.which('chromedriver')
        if path:
            return path
        
        # 常见路径
        common_paths = [
            '/usr/local/bin/chromedriver',
            '/usr/bin/chromedriver',
            './chromedriver',
            '/snap/bin/chromedriver'
        ]
        
        for p in common_paths:
            if os.path.exists(p):
                return p
        
        # 默认路径
        return '/usr/local/bin/chromedriver'

    @retry_on_failure(max_retries=3)
    def login(self):
        """优化的登录主方法"""
        logging.info('开始登陆流程...')
        
        # 尝试多种登录页面URL
        login_urls = [
            "https://hdu.huitu.zhishulib.com/#!/Space/Category/list",
            "https://hdu.huitu.zhishulib.com/",
            "https://hdu.huitu.zhishulib.com/Space/Category/list"
        ]
        
        for url in login_urls:
            try:
                logging.info(f"尝试访问: {url}")
                self.driver.get(url)
                time.sleep(3)
                
                # 保存调试信息
                self.save_debug_info("initial")
                
                # 检查是否需要登录
                if self.is_login_page():
                    result = self.universal_login()
                    if result == 0:
                        return 0
                else:
                    # 可能已经登录
                    cookie_list = self.driver.get_cookies()
                    if cookie_list:
                        self.cookie = ";".join([f"{item['name']}={item['value']}" for item in cookie_list])
                        self.cfg["headers"]['Cookie'] = self.cookie
                        logging.info("使用已有Cookie登录成功")
                        return 0
                        
            except Exception as e:
                logging.error(f"访问 {url} 失败: {e}")
                continue
        
        return -1
    
    def is_login_page(self):
        """判断是否在登录页面"""
        try:
            page_source = self.driver.page_source.lower()
            login_indicators = ['login', '统一认证', 'cas', 'auth', '用户名', '密码', 'signin']
            return any(indicator in page_source for indicator in login_indicators)
        except:
            return True
    
    def universal_login(self):
        """通用登录方法 - 适应各种页面结构"""
        
        # 等待页面稳定
        self.wait_for_page_stable()
        
        # 策略1: 等待iframe并切换
        if self.handle_iframe_login():
            return 0
            
        # 策略2: 多选择器轮询查找
        if self.multi_selector_login():
            return 0
            
        # 策略3: 执行JavaScript注入
        if self.javascript_injection_login():
            return 0
            
        return -1
    
    def wait_for_page_stable(self):
        """等待页面稳定"""
        try:
            # 等待网络空闲
            self.wait.until(lambda driver: driver.execute_script("return document.readyState") == "complete")
            time.sleep(2)
            
            # 等待jQuery（如果存在）
            try:
                self.wait.until(lambda driver: driver.execute_script("return jQuery.active == 0"))
            except:
                pass
        except Exception as e:
            logging.warning(f"等待页面稳定超时: {e}")
    
    def handle_iframe_login(self):
        """处理iframe登录"""
        try:
            # 查找所有iframe
            iframes = self.driver.find_elements(By.TAG_NAME, "iframe")
            iframes.extend(self.driver.find_elements(By.TAG_NAME, "frame"))
            
            logging.info(f"找到 {len(iframes)} 个iframe/frame")
            
            for idx, iframe in enumerate(iframes):
                try:
                    logging.info(f"检查iframe {idx + 1}")
                    self.driver.switch_to.frame(iframe)
                    
                    # 在当前iframe中查找登录表单
                    if self.find_and_fill_login_form():
                        self.driver.switch_to.default_content()
                        return True
                    
                    self.driver.switch_to.default_content()
                except Exception as e:
                    logging.warning(f"切换iframe {idx + 1} 失败: {e}")
                    self.driver.switch_to.default_content()
                    continue
                    
            return False
        except Exception as e:
            logging.error(f"处理iframe失败: {e}")
            return False
    
    def find_and_fill_login_form(self):
        """查找并填写登录表单"""
        try:
            # 查找用户名框
            username_selectors = [
                (By.ID, "username"),
                (By.NAME, "username"),
                (By.CSS_SELECTOR, "input[type='text']"),
                (By.XPATH, "//input[@placeholder]"),
            ]
            
            for selector in username_selectors:
                try:
                    element = self.driver.find_element(*selector)
                    if element.is_displayed() and element.is_enabled():
                        self.fill_input_field(element, self.un)
                        break
                except:
                    continue
            
            # 查找密码框
            password_selectors = [
                (By.ID, "password"),
                (By.NAME, "password"),
                (By.CSS_SELECTOR, "input[type='password']"),
            ]
            
            for selector in password_selectors:
                try:
                    element = self.driver.find_element(*selector)
                    if element.is_displayed() and element.is_enabled():
                        self.fill_input_field(element, self.pd)
                        break
                except:
                    continue
            
            # 查找提交按钮
            submit_selectors = [
                (By.XPATH, "//button[@type='submit']"),
                (By.XPATH, "//input[@type='submit']"),
                (By.XPATH, "//button[contains(text(), '登录')]"),
            ]
            
            for selector in submit_selectors:
                try:
                    element = self.driver.find_element(*selector)
                    if element.is_displayed() and element.is_enabled():
                        self.click_element(element)
                        time.sleep(5)
                        return self.verify_login_success()
                except:
                    continue
            
            return False
        except Exception as e:
            logging.error(f"填写登录表单失败: {e}")
            return False
    
    def multi_selector_login(self):
        """多选择器登录策略"""
        # 更全面的选择器列表
        username_selectors = [
            (By.ID, "username"),
            (By.ID, "userName"), 
            (By.ID, "user_name"),
            (By.ID, "loginName"),
            (By.ID, "account"),
            (By.NAME, "username"),
            (By.NAME, "userName"),
            (By.NAME, "account"),
            (By.CSS_SELECTOR, "input[name='username']"),
            (By.CSS_SELECTOR, "input[name='userName']"),
            (By.XPATH, "//input[@type='text'][@placeholder]"),
            (By.XPATH, "//input[@type='text'][contains(@placeholder, '用户')]"),
            (By.XPATH, "//input[@type='text'][contains(@placeholder, '学号')]"),
            (By.XPATH, "//input[@type='text'][contains(@placeholder, '工号')]"),
            (By.CSS_SELECTOR, "input[type='text']:not([readonly])"),
        ]
        
        password_selectors = [
            (By.ID, "password"),
            (By.ID, "pwd"),
            (By.ID, "passWord"),
            (By.NAME, "password"),
            (By.NAME, "pwd"),
            (By.CSS_SELECTOR, "input[name='password']"),
            (By.XPATH, "//input[@type='password']"),
            (By.CSS_SELECTOR, "input[type='password']"),
        ]
        
        submit_selectors = [
            (By.XPATH, "//button[@type='submit']"),
            (By.XPATH, "//input[@type='submit']"),
            (By.XPATH, "//button[contains(text(), '登录')]"),
            (By.XPATH, "//button[contains(text(), 'Login')]"),
            (By.XPATH, "//input[contains(@value, '登录')]"),
            (By.XPATH, "//button[contains(@class, 'login')]"),
            (By.CSS_SELECTOR, ".login-btn"),
            (By.CSS_SELECTOR, ".btn-login"),
            (By.CSS_SELECTOR, "button[class*='login']"),
        ]
        
        try:
            # 先滚动到页面顶部
            self.driver.execute_script("window.scrollTo(0, 0);")
            time.sleep(0.5)
            
            # 查找用户名框
            username_input = None
            for selector in username_selectors:
                try:
                    elements = self.driver.find_elements(*selector)
                    for elem in elements:
                        if elem.is_displayed() and elem.is_enabled():
                            username_input = elem
                            logging.info(f"找到用户名输入框: {selector}")
                            break
                    if username_input:
                        break
                except:
                    continue
            
            if not username_input:
                logging.error("未找到用户名输入框")
                self.save_debug_info("no_username_field")
                return False
            
            # 填写用户名
            self.fill_input_field(username_input, self.un)
            logging.info("用户名填写成功")
            
            # 查找密码框
            password_input = None
            for selector in password_selectors:
                try:
                    elements = self.driver.find_elements(*selector)
                    for elem in elements:
                        if elem.is_displayed() and elem.is_enabled():
                            password_input = elem
                            logging.info(f"找到密码输入框: {selector}")
                            break
                    if password_input:
                        break
                except:
                    continue
            
            if not password_input:
                logging.error("未找到密码输入框")
                self.save_debug_info("no_password_field")
                return False
            
            # 填写密码
            self.fill_input_field(password_input, self.pd)
            logging.info("密码填写成功")
            
            # 查找提交按钮
            submit_btn = None
            for selector in submit_selectors:
                try:
                    elements = self.driver.find_elements(*selector)
                    for elem in elements:
                        if elem.is_displayed() and elem.is_enabled():
                            submit_btn = elem
                            logging.info(f"找到提交按钮: {selector}")
                            break
                    if submit_btn:
                        break
                except:
                    continue
            
            if not submit_btn:
                logging.error("未找到提交按钮")
                return False
            
            # 点击提交按钮
            self.click_element(submit_btn)
            logging.info("已点击登录按钮")
            
            # 等待登录完成
            time.sleep(5)
            
            # 验证登录结果
            return self.verify_login_success()
            
        except Exception as e:
            logging.error(f"多选择器登录失败: {e}")
            return False
    
    def javascript_injection_login(self):
        """JavaScript注入登录"""
        try:
            # 使用JavaScript查找并填写表单
            js_script = f"""
                var usernameField = null;
                var passwordField = null;
                var submitButton = null;
                
                // 查找用户名输入框
                var selectors = ['input[name="username"]', 'input[name="userName"]', '#username', '#userName', 'input[type="text"]'];
                for (var i = 0; i < selectors.length; i++) {{
                    var field = document.querySelector(selectors[i]);
                    if (field && field.offsetParent !== null) {{
                        usernameField = field;
                        break;
                    }}
                }}
                
                // 查找密码输入框
                selectors = ['input[name="password"]', '#password', '#pwd', 'input[type="password"]'];
                for (var i = 0; i < selectors.length; i++) {{
                    var field = document.querySelector(selectors[i]);
                    if (field && field.offsetParent !== null) {{
                        passwordField = field;
                        break;
                    }}
                }}
                
                // 查找提交按钮
                selectors = ['button[type="submit"]', 'input[type="submit"]', '.login-btn', '.btn-login'];
                for (var i = 0; i < selectors.length; i++) {{
                    var btn = document.querySelector(selectors[i]);
                    if (btn && btn.offsetParent !== null) {{
                        submitButton = btn;
                        break;
                    }}
                }}
                
                if (usernameField && passwordField) {{
                    usernameField.value = '{self.un}';
                    passwordField.value = '{self.pd}';
                    
                    // 触发事件
                    usernameField.dispatchEvent(new Event('input', {{ bubbles: true }}));
                    usernameField.dispatchEvent(new Event('change', {{ bubbles: true }}));
                    passwordField.dispatchEvent(new Event('input', {{ bubbles: true }}));
                    passwordField.dispatchEvent(new Event('change', {{ bubbles: true }}));
                    
                    if (submitButton) {{
                        submitButton.click();
                        return 'clicked';
                    }} else {{
                        // 尝试提交表单
                        var form = usernameField.closest('form');
                        if (form) {{
                            form.submit();
                            return 'submitted';
                        }}
                    }}
                }}
                
                return 'not_found';
            """
            
            result = self.driver.execute_script(js_script)
            logging.info(f"JavaScript登录结果: {result}")
            
            if result in ['clicked', 'submitted']:
                time.sleep(5)
                return self.verify_login_success()
            
            return False
            
        except Exception as e:
            logging.error(f"JavaScript注入登录失败: {e}")
            return False
    
    def fill_input_field(self, element, text):
        """安全地填写输入框"""
        try:
            # 方法1: 清空并输入
            element.clear()
            time.sleep(0.1)
            element.send_keys(text)
            
            # 方法2: 如果方法1失败，使用JavaScript
            if element.get_attribute('value') != text:
                self.driver.execute_script(f"arguments[0].value = '{text}';", element)
                
                # 触发输入事件
                self.driver.execute_script("""
                    arguments[0].dispatchEvent(new Event('input', { bubbles: true }));
                    arguments[0].dispatchEvent(new Event('change', { bubbles: true }));
                """, element)
                
        except Exception as e:
            logging.error(f"填写输入框失败: {e}")
            # 最终尝试：直接JavaScript设置
            self.driver.execute_script(f"arguments[0].value = '{text}';", element)
    
    def click_element(self, element):
        """安全地点击元素"""
        try:
            # 滚动到元素可见
            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
            time.sleep(0.3)
            
            # 尝试普通点击
            element.click()
        except:
            try:
                # 使用JavaScript点击
                self.driver.execute_script("arguments[0].click();", element)
            except Exception as e:
                logging.error(f"点击元素失败: {e}")
                raise
    
    def verify_login_success(self):
        """验证登录是否成功"""
        time.sleep(3)
        
        # 检查URL
        current_url = self.driver.current_url
        logging.info(f"登录后URL: {current_url}")
        
        # 检查是否在目标网站
        if "hdu.huitu.zhishulib.com" in current_url:
            # 获取Cookie
            cookie_list = self.driver.get_cookies()
            if cookie_list:
                self.cookie = ";".join([f"{item['name']}={item['value']}" for item in cookie_list])
                self.cfg["headers"]['Cookie'] = self.cookie
                logging.info("登录验证成功")
                return True
        
        # 检查页面是否包含错误信息
        try:
            page_source = self.driver.page_source.lower()
            error_keywords = ['用户名或密码错误', '登录失败', 'invalid', 'error']
            for keyword in error_keywords:
                if keyword in page_source:
                    logging.error(f"登录失败: 页面包含错误信息 '{keyword}'")
                    return False
        except:
            pass
        
        # 尝试访问需要登录的页面
        try:
            self.driver.get("https://hdu.huitu.zhishulib.com/#!/Space/Category/list")
            time.sleep(3)
            if "hdu.huitu.zhishulib.com" in self.driver.current_url:
                cookie_list = self.driver.get_cookies()
                if cookie_list:
                    self.cookie = ";".join([f"{item['name']}={item['value']}" for item in cookie_list])
                    self.cfg["headers"]['Cookie'] = self.cookie
                    return True
        except Exception as e:
            logging.error(f"验证登录时出错: {e}")
        
        return False
    
    def save_debug_info(self, suffix=""):
        """保存调试信息"""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"debug_{timestamp}_{suffix}.html" if suffix else f"debug_{timestamp}.html"
            
            with open(filename, "w", encoding="utf-8") as f:
                f.write(self.driver.page_source)
            
            screenshot_name = f"screenshot_{timestamp}_{suffix}.png" if suffix else f"screenshot_{timestamp}.png"
            self.driver.save_screenshot(screenshot_name)
            
            logging.info(f"调试信息已保存到 {filename} 和 {screenshot_name}")
        except Exception as e:
            logging.error(f"保存调试信息失败: {e}")

    @retry_on_failure(max_retries=3)
    def get_user_info(self):
        logging.info('获取用户信息...')
        headers = self.cfg["headers"]
        headers['Cookie'] = self.cookie
        try:
            resp = requests.get("https://hdu.huitu.zhishulib.com/Seat/Index/searchSeats?LAB_JSON=1", headers=headers)
            self.user_data = resp.json()['DATA']
            if 'uid' not in self.user_data:
                 raise KeyError("Response JSON does not contain 'uid'")
            logging.info("获取用户数据成功")
            return 0
        except Exception as e:
            logging.error(f"获取用户数据失败: {e}")
            logging.error(f"收到的响应: {resp.text if 'resp' in locals() else 'No response'}")
            return -1

    def book_seat(self, start_hour, duration_hours, user_config):
        logging.info(f'开始抢座: {start_hour}:00, 持续 {duration_hours} 小时')
        seat_to_book = user_config['自定义'][0]
        
        # 使用北京时间来计算预约时间
        tz_cst = ZoneInfo("Asia/Shanghai")
        cst_now = datetime.now(tz_cst)
        
        # 计算明天北京时间的预约时间点
        if cst_now.hour >= TARGET_HOUR:
            book_date_cst = cst_now + timedelta(days=1)
        else:
            book_date_cst = cst_now
        
        book_time_cst = book_date_cst.replace(hour=start_hour, minute=0, second=0, microsecond=0)
        
        # 转换为UTC时间戳
        book_time_utc = book_time_cst.astimezone(ZoneInfo("UTC"))
        
        # 计算Unix时间戳
        api_epoch_utc = datetime(1970, 1, 1, tzinfo=ZoneInfo("UTC"))
        delta = book_time_utc - api_epoch_utc
        total_seconds = int(delta.total_seconds())
        
        logging.info(f"预约时间: 北京时间 {book_time_cst.strftime('%Y-%m-%d %H:%M:%S')} -> UTC时间戳 {total_seconds}")
        
        data = f"beginTime={total_seconds}&duration={3600 * duration_hours}&seats[0]={seat_to_book}&seatBookers[0]={self.user_data['uid']}"
        headers = self.cfg["headers"]
        headers['Cookie'] = self.cookie
        logging.info(data)
        
        for i in range(3):
            try:
                logging.info(f"第 {i+1}/3 次尝试抢座: {start_hour}:00...")
                resp = requests.post(self.cfg["target"], data=data, headers=headers)
                resp_json = resp.json()
                logging.info(f"收到响应: {resp_json}")
                if resp_json.get("CODE") == "ok":
                    message = f"成功抢到座位: {seat_to_book} at {start_hour}:00"
                    logging.info(message)
                    return True, message
                else:
                    time.sleep(0.5)
            except Exception as e:
                logging.error(f"请求时发生错误: {e}")
                time.sleep(1)

        final_message = f"抢座失败: {start_hour}:00 - {resp_json.get('MESSAGE', '未知错误')}"
        logging.warning(final_message)
        return False, final_message

    def wechatNotice(self, title, desp):
        logging.info('发送 Server酱 通知')
        if self.SCKey:
            url = f'https://sctapi.ftqq.com/{self.SCKey}.send'
            data = {'title': title, 'desp': desp}
            try:
                r = requests.post(url, data=data)
                result = r.json()
                if result.get("data", {}).get("error") == 'SUCCESS':
                    print("Server酱通知成功")
                else:
                    print(f"Server酱通知失败: {result}")
            except Exception as e:
                logging.error(f"推送服务配置错误: {e}")
    
    def quit(self):
        """安全退出浏览器"""
        try:
            self.driver.quit()
        except:
            pass


if __name__ == "__main__":
    logging.info('====== 开始执行抢座脚本 ======')
    
    try:
        with open("user_config.yml", 'r', encoding='utf-8') as f_obj:
            user_config = yaml.safe_load(f_obj)
        with open("config/basic_config.yml", 'r', encoding='utf-8') as f_obj:
            basic_config = yaml.safe_load(f_obj)
    except Exception as e:
        logging.error(f"读取配置文件失败: {e}")
        exit(-1)

    if not user_config.get('enabled', False):
        logging.info('抢座功能未在 user_config.yml 中启用，脚本退出。')
        exit(0)

    s = SeatAutoBooker(basic_config["SeatAutoBooker"])
    
    try:
        # 登录重试逻辑
        login_success = False
        for attempt in range(3):
            logging.info(f"第 {attempt + 1}/3 次尝试登录...")
            if s.login() == 0:
                login_success = True
                break
            else:
                if attempt < 2:
                    logging.warning(f"登录失败，{5}秒后重试...")
                    time.sleep(5)
                
        if not login_success:
            error_msg = "登录失败，已尝试3次，请检查账号密码或网站更新。"
            s.wechatNotice("HDU抢座失败", error_msg)
            logging.error(error_msg)
            s.quit()
            exit(-1)
        
        # 获取用户信息重试逻辑
        user_info_success = False
        for attempt in range(3):
            logging.info(f"第 {attempt + 1}/3 次尝试获取用户信息...")
            if s.get_user_info() == 0:
                user_info_success = True
                break
            else:
                if attempt < 2:
                    logging.warning(f"获取用户信息失败，{3}秒后重试...")
                    time.sleep(3)
                            
        if not user_info_success:
            error_msg = "获取用户信息失败，已尝试3次，Cookie可能已过期。"
            s.wechatNotice("HDU抢座失败", error_msg)
            logging.error(error_msg)
            s.quit()
            exit(-1)

        # 等待到目标时间
        tz_cst = ZoneInfo("Asia/Shanghai")
        logging.info(f"登录成功，准备等待到北京时间 {TARGET_HOUR:02d}:{TARGET_MINUTE:02d} 进行抢座...")
        
        now_cst = datetime.now(tz_cst)
        target_time = now_cst.replace(hour=TARGET_HOUR, minute=TARGET_MINUTE, second=0, microsecond=0)
        
        # 如果当前时间已经超过目标时间，则设置为明天
        if now_cst >= target_time:
            target_time = target_time + timedelta(days=1)
            logging.info(f"当前时间已超过今日目标时间，将等待到明天 {target_time.strftime('%Y-%m-%d %H:%M:%S')}")

        while True:
            current_time_cst = datetime.now(tz_cst)
            if current_time_cst >= target_time:
                logging.info(f"北京时间 {current_time_cst.strftime('%H:%M:%S')} 已到，开始执行抢座！")
                break
            
            remaining_seconds = (target_time - current_time_cst).total_seconds()
            
            if remaining_seconds > 10:
                if int(remaining_seconds) % 10 == 0:
                    logging.info(f"等待中... 距离目标时间还剩 {remaining_seconds:.0f} 秒")
                time.sleep(1)
            else:
                time.sleep(0.05)
        
        # 执行抢座
        results = []
        success1, msg1 = s.book_seat(start_hour=9, duration_hours=13, user_config=user_config)
        
        # 发送通知
        if success1:
            s.wechatNotice("HDU抢座成功", msg1)
        else:
            s.wechatNotice("HDU抢座失败", msg1)
            
        logging.info('====== 脚本执行完毕 ======')
        
    except Exception as e:
        logging.error(f"脚本执行出错: {e}")
        s.wechatNotice("HDU抢座异常", f"脚本执行出错: {str(e)}")
    finally:
        s.quit()
