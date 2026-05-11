import requests
import yaml
from datetime import datetime, timedelta
import json
import os
import logging
import time

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
        # 添加更多选项以提高稳定性
        chrome_options.add_argument('--disable-blink-features=AutomationControlled')
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option('useAutomationExtension', False)
        
        self.driver = webdriver.Chrome(service=Service('/usr/local/bin/chromedriver'), options=chrome_options)
        self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        self.wait = WebDriverWait(self.driver, 20, 0.5)  # 增加等待时间
        self.cookie = None
        self.cfg = booker_config
        self.session = None  # 添加session对象

    def login(self):
        logging.info('开始登陆...')
        try:
            self.driver.get("https://hdu.huitu.zhishulib.com/#!/Space/Category/list")
            logging.info('成功打开HDU统一认证登录页面.')
            
            # 等待页面完全加载
            time.sleep(3)
            
            # 使用更灵活的元素定位策略
            return self.enhanced_login_flow()
                
        except Exception as e:
            logging.error(f"登录流程失败：{e}")
            # 保存截图以便调试
            self.driver.save_screenshot("login_initial_error.png")
            return -1

    def enhanced_login_flow(self):
        """增强的登录流程，包含多种尝试策略"""
        max_attempts = 3
        for attempt in range(max_attempts):
            try:
                logging.info(f"尝试第 {attempt + 1}/{max_attempts} 种登录策略...")
                
                # 策略1: 使用JavaScript直接操作元素
                if self.login_with_javascript():
                    return 0
                    
                # 策略2: 使用传统方式但增加等待
                time.sleep(2)
                if self.login_with_enhanced_wait():
                    return 0
                    
                # 策略3: 刷新页面重试
                if attempt < max_attempts - 1:
                    logging.info("刷新页面重试...")
                    self.driver.refresh()
                    time.sleep(3)
                    
            except Exception as e:
                logging.error(f"第 {attempt + 1} 种策略失败: {e}")
                if attempt < max_attempts - 1:
                    time.sleep(2)
        
        logging.error("所有登录策略都失败了")
        self.driver.save_screenshot("login_all_strategies_failed.png")
        return -1

    def login_with_javascript(self):
        """使用JavaScript直接操作元素的登录方式"""
        try:
            logging.info("尝试使用JavaScript登录...")
            
            # 使用JavaScript查找并操作元素
            username_script = """
            var inputs = document.querySelectorAll('input[type="text"], input[name="username"], input[id="username"]');
            for (var i = 0; i < inputs.length; i++) {
                if (inputs[i].offsetParent !== null) {
                    return inputs[i];
                }
            }
            return null;
            """
            
            password_script = """
            var inputs = document.querySelectorAll('input[type="password"], input[name="password"], input[id="password"]');
            for (var i = 0; i < inputs.length; i++) {
                if (inputs[i].offsetParent !== null) {
                    return inputs[i];
                }
            }
            return null;
            """
            
            submit_script = """
            var buttons = document.querySelectorAll('button[type="submit"], input[type="submit"], .btn-submit, .login-btn');
            for (var i = 0; i < buttons.length; i++) {
                if (buttons[i].offsetParent !== null && buttons[i].disabled === false) {
                    return buttons[i];
                }
            }
            return null;
            """
            
            # 查找用户名输入框
            username_element = self.driver.execute_script(username_script)
            if not username_element:
                logging.warning("JavaScript未找到用户名输入框")
                return False
                
            # 使用JavaScript设置用户名
            self.driver.execute_script("arguments[0].value = arguments[1];", username_element, self.un)
            logging.info('JavaScript设置用户名成功')
            
            # 查找密码输入框
            password_element = self.driver.execute_script(password_script)
            if not password_element:
                logging.warning("JavaScript未找到密码输入框")
                return False
                
            # 使用JavaScript设置密码
            self.driver.execute_script("arguments[0].value = arguments[1];", password_element, self.pd)
            logging.info('JavaScript设置密码成功')
            
            # 查找提交按钮
            submit_element = self.driver.execute_script(submit_script)
            if not submit_element:
                logging.warning("JavaScript未找到提交按钮")
                return False
                
            # 使用JavaScript点击提交按钮
            self.driver.execute_script("arguments[0].click();", submit_element)
            logging.info('JavaScript点击登录按钮成功')
            
            # 等待登录完成
            time.sleep(5)
            
            # 检查是否登录成功
            if self.check_login_success():
                return True
            else:
                logging.warning("JavaScript登录后未成功跳转")
                return False
                
        except Exception as e:
            logging.error(f"JavaScript登录失败: {e}")
            return False

    def login_with_enhanced_wait(self):
        """使用增强等待的传统登录方式"""
        try:
            logging.info("尝试使用增强等待登录...")
            
            # 定义多种可能的选择器
            username_selectors = [
                (By.ID, "username"),
                (By.NAME, "username"),
                (By.XPATH, "//input[@type='text']"),
                (By.XPATH, "//input[contains(@placeholder, '用户')]"),
                (By.XPATH, "//input[contains(@placeholder, '学工')]"),
                (By.CSS_SELECTOR, "input[type='text']")
            ]
            
            password_selectors = [
                (By.ID, "password"),
                (By.NAME, "password"), 
                (By.XPATH, "//input[@type='password']"),
                (By.CSS_SELECTOR, "input[type='password']")
            ]
            
            submit_selectors = [
                (By.CLASS_NAME, "btn-submit"),
                (By.XPATH, "//button[@type='submit']"),
                (By.XPATH, "//input[@type='submit']"),
                (By.XPATH, "//button[contains(text(), '登录')]"),
                (By.XPATH, "//input[contains(@value, '登录')]"),
                (By.CSS_SELECTOR, "button[type='submit']")
            ]
            
            # 查找并操作用户名输入框
            username_element = self.find_element_with_retry(username_selectors)
            if not username_element:
                raise Exception("未找到用户名输入框")
                
            # 清空并缓慢输入用户名
            username_element.clear()
            for char in self.un:
                username_element.send_keys(char)
                time.sleep(0.05)
            logging.info('输入用户名成功')
            
            # 查找并操作密码输入框
            password_element = self.find_element_with_retry(password_selectors)
            if not password_element:
                raise Exception("未找到密码输入框")
                
            # 清空并缓慢输入密码
            password_element.clear()
            for char in self.pd:
                password_element.send_keys(char)
                time.sleep(0.05)
            logging.info('输入密码成功')
            
            # 等待一下让界面响应
            time.sleep(1)
            
            # 查找并点击提交按钮
            submit_element = self.find_element_with_retry(submit_selectors)
            if not submit_element:
                raise Exception("未找到提交按钮")
                
            # 使用JavaScript点击避免状态问题
            self.driver.execute_script("arguments[0].click();", submit_element)
            logging.info('点击登录按钮成功')
            
            # 等待登录完成
            time.sleep(5)
            
            # 检查是否登录成功
            return self.check_login_success()
            
        except Exception as e:
            logging.error(f"增强等待登录失败: {e}")
            return False

    def find_element_with_retry(self, selectors, max_attempts=3):
        """使用多种选择器重试查找元素"""
        for attempt in range(max_attempts):
            for selector in selectors:
                try:
                    element = self.driver.find_element(*selector)
                    if element.is_displayed() and element.is_enabled():
                        logging.info(f"找到元素: {selector}")
                        return element
                except (NoSuchElementException, ElementNotInteractableException):
                    continue
            if attempt < max_attempts - 1:
                time.sleep(1)
        return None

    def check_login_success(self):
        """检查登录是否成功 - 改进版"""
        # 等待页面完全跳转
        time.sleep(3)
        
        current_url = self.driver.current_url
        logging.info(f"当前URL: {current_url}")
        
        if "hdu.huitu.zhishulib.com" in current_url:
            logging.info("成功跳转到目标网站")
            
            # 改进Cookie获取方式
            cookie_list = self.driver.get_cookies()
            
            # 创建requests Session并设置Cookie
            self.session = requests.Session()
            for cookie in cookie_list:
                self.session.cookies.set(cookie['name'], cookie['value'], domain=cookie.get('domain', ''))
            
            # 构建Cookie字符串（用于原有headers）
            cookie_strings = []
            for item in cookie_list:
                cookie_strings.append(f"{item['name']}={item['value']}")
            self.cookie = "; ".join(cookie_strings)
            
            # 更新headers中的Cookie
            self.cfg["headers"]['Cookie'] = self.cookie
            self.cfg["headers"]['User-Agent'] = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            self.cfg["headers"]['X-Requested-With'] = 'XMLHttpRequest'
            
            logging.info(f"登录成功！获取到 {len(cookie_list)} 个Cookie")
            return True
        else:
            logging.warning(f"尚未跳转到目标网站，当前URL: {current_url}")
            return False

    def get_user_info(self):
        """获取用户信息 - 改进版"""
        logging.info('获取用户信息...')
        
        tz_cst = ZoneInfo("Asia/Shanghai")
        now = datetime.now(tz_cst)
        
        # 使用正确的参数格式
        params = {
            'LAB_JSON': '1',
            't': int(time.time() * 1000)  # 添加时间戳参数
        }
        
        headers = self.cfg["headers"].copy()
        headers['Cookie'] = self.cookie
        headers['User-Agent'] = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        headers['X-Requested-With'] = 'XMLHttpRequest'
        headers['Referer'] = 'https://hdu.huitu.zhishulib.com/#!/Space/Category/list'
        
        try:
            # 方法1：使用requests
            url = "https://hdu.huitu.zhishulib.com/Seat/Index/searchSeats"
            
            # 优先使用session
            if self.session:
                resp = self.session.get(url, headers=headers, params=params, timeout=10)
            else:
                resp = requests.get(url, headers=headers, params=params, timeout=10)
            
            logging.info(f"响应状态码: {resp.status_code}")
            logging.info(f"响应内容预览: {resp.text[:200]}")
            
            if resp.status_code == 200:
                resp_json = resp.json()
                logging.info(f"完整响应: {resp_json}")
                
                # 检查响应结构
                if 'DATA' in resp_json and resp_json['DATA']:
                    self.user_data = resp_json['DATA']
                    if 'uid' in self.user_data:
                        logging.info(f"获取用户数据成功，用户ID: {self.user_data['uid']}")
                        return 0
                    else:
                        logging.error(f"响应中缺少'uid'字段，DATA内容: {self.user_data}")
                elif 'uid' in resp_json:
                    # 直接在根节点找到uid
                    self.user_data = resp_json
                    logging.info(f"直接在根节点找到用户ID: {self.user_data['uid']}")
                    return 0
                else:
                    logging.error(f"响应结构异常，keys: {resp_json.keys() if isinstance(resp_json, dict) else 'not a dict'}")
            else:
                logging.error(f"HTTP请求失败，状态码: {resp.status_code}")
                # 尝试使用Selenium
                return self.get_user_info_selenium()
                
        except requests.exceptions.RequestException as e:
            logging.error(f"requests请求失败: {e}")
            return self.get_user_info_selenium()
        except json.JSONDecodeError as e:
            logging.error(f"JSON解析失败: {e}")
            logging.error(f"原始响应: {resp.text if 'resp' in locals() else 'No response'}")
            return self.get_user_info_selenium()
        
        return -1

    def get_user_info_selenium(self):
        """使用Selenium作为备用方案获取用户信息"""
        logging.info("尝试使用Selenium获取用户信息...")
        try:
            # 确保在正确的页面
            if not self.driver.current_url.startswith("https://hdu.huitu.zhishulib.com"):
                self.driver.get("https://hdu.huitu.zhishulib.com/#!/Space/Category/list")
                time.sleep(3)
            
            # 执行JavaScript获取用户信息
            script = """
            // 尝试从localStorage或sessionStorage获取用户信息
            try {
                var userData = localStorage.getItem('user_data');
                if (userData) {
                    return JSON.parse(userData);
                }
                
                // 尝试从页面变量中获取
                if (window.userInfo) {
                    return window.userInfo;
                }
                
                // 发送请求获取用户信息
                var xhr = new XMLHttpRequest();
                xhr.open('GET', '/Seat/Index/searchSeats?LAB_JSON=1&t=' + new Date().getTime(), false);
                xhr.setRequestHeader('X-Requested-With', 'XMLHttpRequest');
                xhr.send(null);
                if (xhr.status === 200) {
                    return JSON.parse(xhr.responseText);
                }
            } catch(e) {
                return {'error': e.toString()};
            }
            return null;
            """
            
            result = self.driver.execute_script(script)
            if result and 'DATA' in result and result['DATA']:
                self.user_data = result['DATA']
                if 'uid' in self.user_data:
                    logging.info(f"Selenium成功获取用户信息: {self.user_data['uid']}")
                    return 0
            elif result and 'uid' in result:
                self.user_data = result
                logging.info(f"Selenium直接在根节点获取用户信息: {self.user_data['uid']}")
                return 0
                
        except Exception as e:
            logging.error(f"Selenium获取用户信息失败: {e}")
        
        return -1

    def refresh_cookie(self):
        """刷新Cookie"""
        logging.info("刷新Cookie...")
        try:
            # 访问页面刷新Cookie
            self.driver.refresh()
            time.sleep(2)
            
            # 重新获取Cookie
            cookie_list = self.driver.get_cookies()
            
            # 更新session
            if self.session:
                self.session.cookies.clear()
                for cookie in cookie_list:
                    self.session.cookies.set(cookie['name'], cookie['value'], domain=cookie.get('domain', ''))
            
            # 更新Cookie字符串
            cookie_strings = [f"{item['name']}={item['value']}" for item in cookie_list]
            self.cookie = "; ".join(cookie_strings)
            self.cfg["headers"]['Cookie'] = self.cookie
            
            logging.info(f"Cookie刷新成功，获取到 {len(cookie_list)} 个Cookie")
            return True
        except Exception as e:
            logging.error(f"Cookie刷新失败: {e}")
            return False

    def debug_cookie(self):
        """调试Cookie内容"""
        logging.info("=== Cookie调试信息 ===")
        cookie_list = self.driver.get_cookies()
        for cookie in cookie_list:
            logging.info(f"Name: {cookie['name']}, Domain: {cookie.get('domain', 'N/A')}, "
                        f"HttpOnly: {cookie.get('httpOnly', False)}")
        
        # 检查Cookie是否有效
        test_url = "https://hdu.huitu.zhishulib.com/Seat/Index/searchSeats?LAB_JSON=1"
        headers = self.cfg["headers"].copy()
        headers['Cookie'] = self.cookie
        
        try:
            resp = requests.get(test_url, headers=headers, timeout=5)
            logging.info(f"Cookie测试响应状态: {resp.status_code}")
            if resp.status_code == 200:
                logging.info("Cookie有效")
                return True
            else:
                logging.warning("Cookie可能过期")
                return False
        except Exception as e:
            logging.error(f"Cookie测试失败: {e}")
            return False

    def book_seat(self, start_hour, duration_hours, user_config):
        """优化后的抢座方法"""
        logging.info(f'开始抢座: {start_hour}:00, 持续 {duration_hours} 小时')
        seat_to_book = user_config['自定义'][0]
        
        # 使用北京时间来计算预约时间
        tz_cst = ZoneInfo("Asia/Shanghai")
        cst_now = datetime.now(tz_cst)
        
        # 计算明天北京时间的预约时间点
        book_date_cst = cst_now + timedelta(days=2)
        book_time_cst = book_date_cst.replace(hour=start_hour, minute=0, second=0, microsecond=0)
        
        # 转换为UTC时间戳
        book_time_utc = book_time_cst.astimezone(ZoneInfo("UTC"))
        
        # 计算Unix时间戳（秒级）
        api_epoch_utc = datetime(1970, 1, 1, tzinfo=ZoneInfo("UTC"))
        delta = book_time_utc - api_epoch_utc
        begin_timestamp = int(delta.total_seconds())
        
        logging.info(f"预约时间: 北京时间 {book_time_cst.strftime('%Y-%m-%d %H:%M:%S')} -> UTC时间戳 {begin_timestamp}")
        
        # 使用字典构造POST数据
        post_data = {
            'beginTime': str(begin_timestamp),
            'duration': str(3600 * duration_hours),
            'seats[0]': str(seat_to_book),
            'seatBookers[0]': str(self.user_data['uid'])
        }
        
        # 准备请求头
        headers = self.cfg["headers"].copy()
        headers['Cookie'] = self.cookie
        headers['Content-Type'] = 'application/x-www-form-urlencoded; charset=UTF-8'
        headers['Origin'] = 'https://hdu.huitu.zhishulib.com'
        headers['Referer'] = 'https://hdu.huitu.zhishulib.com/#!/Space/Category/list'
        headers['Accept'] = 'application/json, text/javascript, */*; q=0.01'
        headers['X-Requested-With'] = 'XMLHttpRequest'
        
        logging.info(f"请求URL: {self.cfg['target']}")
        logging.info(f"请求数据: {post_data}")
        # 不打印完整的cookie以避免泄露，只打印长度
        logging.info(f"Cookie长度: {len(self.cookie)} 字符")
        
        for i in range(3):
            try:
                logging.info(f"第 {i+1}/3 次尝试抢座: {start_hour}:00...")
                
                # 记录请求开始时间
                start_time = time.time()
                
                # 使用session发送POST请求
                if self.session:
                    resp = self.session.post(
                        self.cfg["target"], 
                        data=post_data,
                        headers=headers,
                        timeout=10
                    )
                else:
                    resp = requests.post(
                        self.cfg["target"], 
                        data=post_data,
                        headers=headers,
                        timeout=10
                    )
                
                # 计算请求耗时
                elapsed_time = (time.time() - start_time) * 1000
                logging.info(f"请求耗时: {elapsed_time:.2f}ms")
                logging.info(f"响应状态码: {resp.status_code}")
                logging.info(f"响应头: {dict(resp.headers)}")
                logging.info(f"原始响应内容: {resp.text}")
                
                # 处理可能的空响应或非JSON响应
                if not resp.text or resp.text.strip() == '':
                    logging.error("收到空响应")
                    time.sleep(1)
                    continue
                
                # 尝试解析JSON
                try:
                    resp_json = resp.json()
                    logging.info(f"解析后的响应: {json.dumps(resp_json, ensure_ascii=False)}")
                except json.JSONDecodeError as e:
                    logging.error(f"JSON解析失败: {e}")
                    logging.error(f"原始响应内容: {resp.text}")
                    # 如果响应不是JSON，可能是HTML错误页面
                    if "login" in resp.text.lower() or "认证" in resp.text:
                        logging.error("检测到登录页面，Cookie可能已过期")
                        self.refresh_cookie()
                        headers['Cookie'] = self.cookie
                        time.sleep(2)
                    continue
                
                # 检查多种可能的成功状态码
                code = resp_json.get("CODE") or resp_json.get("code") or resp_json.get("status")
                message = resp_json.get("MESSAGE") or resp_json.get("message") or resp_json.get("msg", "未知错误")
                
                # 检查是否成功
                if code == "ok" or code == "success" or code == 200 or code == 0:
                    success_msg = f"✅ 成功抢到座位: {seat_to_book} at {start_hour}:00，持续{duration_hours}小时"
                    logging.info(success_msg)
                    return True, success_msg
                else:
                    logging.warning(f"抢座失败 - 状态码: {code}, 消息: {message}")
                    
                    # 如果cookie过期，尝试刷新
                    if "登录" in str(message) or "login" in str(message).lower() or "session" in str(message).lower() or "认证" in str(message):
                        logging.info("检测到登录状态失效，尝试刷新Cookie...")
                        self.refresh_cookie()
                        headers['Cookie'] = self.cookie
                        time.sleep(2)
                    elif "已预约" in str(message) or "已存在" in str(message) or "already" in str(message).lower():
                        logging.warning("该时间段可能已预约过")
                        return False, f"预约失败: {message}"
                    else:
                        time.sleep(0.5)
                        
            except requests.exceptions.Timeout:
                logging.error(f"第 {i+1} 次请求超时")
                time.sleep(1)
            except requests.exceptions.ConnectionError as e:
                logging.error(f"第 {i+1} 次连接错误: {e}")
                time.sleep(2)
            except Exception as e:
                logging.error(f"第 {i+1} 次请求发生错误: {e}")
                import traceback
                logging.error(traceback.format_exc())
                time.sleep(1)
        
        final_message = f"❌ 抢座失败: {start_hour}:00，已重试3次"
        logging.warning(final_message)
        return False, final_message

    def wechatNotice(self, title, desp):
        logging.info('发送 Server酱 通知')
        if self.SCKey:
            url = f'https://sctapi.ftqq.com/{self.SCKey}.send'
            data = {'title': title, 'desp': desp}
            try:
                r = requests.post(url, data=data, timeout=5)
                result = r.json()
                if result.get("data", {}).get("error") == 'SUCCESS':
                    print("Server酱通知成功")
                else:
                    print(f"Server酱通知失败: {result}")
            except Exception as e:
                logging.error(f"推送服务配置错误: {e}")

    def close(self):
        """关闭浏览器驱动"""
        try:
            if self.driver:
                self.driver.quit()
                logging.info("浏览器驱动已关闭")
        except Exception as e:
            logging.error(f"关闭浏览器驱动时出错: {e}")


if __name__ == "__main__":
    logging.info('====== 开始执行抢座脚本 ======')
    
    try:
        with open("user_config.yml", 'r', encoding='utf-8') as f_obj:
            user_config = yaml.safe_load(f_obj)
        with open("config/basic_config.yml", 'r', encoding='utf-8') as f_obj:
            basic_config = yaml.safe_load(f_obj)
    except FileNotFoundError as e:
        logging.error(f"配置文件未找到: {e}")
        exit(-1)
    except yaml.YAMLError as e:
        logging.error(f"配置文件解析错误: {e}")
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
            s.close()
            exit(-1)
        
        # 调试Cookie
        s.debug_cookie()
        
        # 获取用户信息重试逻辑 - 增加Cookie刷新
        user_info_success = False
        for attempt in range(3):
            logging.info(f"第 {attempt + 1}/3 次尝试获取用户信息...")
            
            # 如果前一次失败，尝试刷新Cookie
            if attempt > 0:
                logging.info("尝试刷新Cookie...")
                s.refresh_cookie()
                time.sleep(2)
            
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
            s.close()
            exit(-1)

        # 等待到目标时间
        tz_cst = ZoneInfo("Asia/Shanghai")
        logging.info(f"登录成功，准备等待到北京时间 {TARGET_HOUR:02d}:{TARGET_MINUTE:02d} 进行抢座...")
        
        now_cst = datetime.now(tz_cst)
        target_time = now_cst.replace(hour=TARGET_HOUR, minute=TARGET_MINUTE, second=0, microsecond=0)
        
        # 如果当前时间已经超过目标时间，推迟到明天
        if now_cst > target_time:
            target_time = target_time + timedelta(days=1)
            logging.info(f"当前时间已超过目标时间，将目标时间设为明天: {target_time.strftime('%Y-%m-%d %H:%M:%S')}")

        while True:
            current_time_cst = datetime.now(tz_cst)
            if current_time_cst >= target_time:
                logging.info(f"北京时间 {current_time_cst.strftime('%H:%M:%S')} 已到，开始执行抢座！")
                break
            
            remaining_seconds = (target_time - current_time_cst).total_seconds()
            
            if int(remaining_seconds) % 10 == 0 and int(remaining_seconds) > 0:
                logging.info(f"等待中... 距离目标时间还剩 {remaining_seconds:.0f} 秒")
                time.sleep(1)
            elif remaining_seconds < 10:
                time.sleep(0.05)
            else:
                time.sleep(1)
        
        # 执行抢座
        results = []
        
        # 抢8:00开始的座位，持续13小时
        success1, msg1 = s.book_seat(start_hour=8, duration_hours=13, user_config=user_config)
        results.append(msg1)
        
        # 可以在这里添加更多时段的抢座
        # success2, msg2 = s.book_seat(start_hour=13, duration_hours=8, user_config=user_config)
        # results.append(msg2)
        
        # 发送最终结果通知
        final_message = "\n".join(results)
        if any("成功" in msg for msg in results):
            s.wechatNotice("HDU抢座结果", f"🎉 部分或全部抢座成功！\n\n{final_message}")
        else:
            s.wechatNotice("HDU抢座结果", f"❌ 抢座失败！\n\n{final_message}")
        
        logging.info('====== 脚本执行完毕 ======')
        
    except KeyboardInterrupt:
        logging.info("用户中断脚本执行")
    except Exception as e:
        logging.error(f"脚本执行过程中发生未预期的错误: {e}")
        import traceback
        logging.error(traceback.format_exc())
        s.wechatNotice("HDU抢座异常", f"脚本执行异常: {str(e)}")
    finally:
        s.close()
