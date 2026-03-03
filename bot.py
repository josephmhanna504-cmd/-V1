
import asyncio
import logging
import os
import random
import re
from datetime import datetime

import aiosqlite
from aiogram import Bot, Dispatcher, Router, F, types
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.client.default import DefaultBotProperties

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Bot token from environment variable
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TELEGRAM_TOKEN:
    raise ValueError("TELEGRAM_TOKEN environment variable not set")

# Database file
DB_FILE = "capitals_quiz.db"

# --- Database Functions ---

async def init_db():
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                total_questions INTEGER DEFAULT 0,
                correct_answers INTEGER DEFAULT 0,
                learned_capitals TEXT DEFAULT ''
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                country TEXT,
                user_answer TEXT,
                correct_answer TEXT,
                is_correct INTEGER,
                level TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.commit()

async def get_user(user_id: int):
    async with aiosqlite.connect(DB_FILE) as db:
        cursor = await db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        user = await cursor.fetchone()
        if user:
            return {
                "user_id": user[0],
                "total_questions": user[1],
                "correct_answers": user[2],
                "learned_capitals": user[3].split(',') if user[3] else []
            }
        return None

async def create_user(user_id: int):
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
        await db.commit()

async def update_user_stats(user_id: int, is_correct: bool):
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("UPDATE users SET total_questions = total_questions + 1, correct_answers = correct_answers + ? WHERE user_id = ?", (1 if is_correct else 0, user_id,))
        await db.commit()

async def add_history_entry(user_id: int, country: str, user_answer: str, correct_answer: str, is_correct: bool, level: str):
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("INSERT INTO history (user_id, country, user_answer, correct_answer, is_correct, level) VALUES (?, ?, ?, ?, ?, ?)",
                         (user_id, country, user_answer, correct_answer, 1 if is_correct else 0, level))
        await db.commit()

async def get_user_history(user_id: int, limit: int = 10):
    async with aiosqlite.connect(DB_FILE) as db:
        cursor = await db.execute("SELECT country, user_answer, correct_answer, is_correct, timestamp FROM history WHERE user_id = ? ORDER BY timestamp DESC LIMIT ?", (user_id, limit,))
        return await cursor.fetchall()

async def get_wrong_answers_count(user_id: int):
    async with aiosqlite.connect(DB_FILE) as db:
        cursor = await db.execute("SELECT country, COUNT(*) FROM history WHERE user_id = ? AND is_correct = 0 GROUP BY country ORDER BY COUNT(*) DESC LIMIT 5", (user_id,))
        return await cursor.fetchall()

async def reset_user_stats(user_id: int):
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("UPDATE users SET total_questions = 0, correct_answers = 0, learned_capitals = '' WHERE user_id = ?", (user_id,))
        await db.execute("DELETE FROM history WHERE user_id = ?", (user_id,))
        await db.commit()

async def update_learned_capitals(user_id: int, learned_capitals: list[str]):
    async with aiosqlite.connect(DB_FILE) as db:
        learned_str = ','.join(learned_capitals)
        await db.execute("UPDATE users SET learned_capitals = ? WHERE user_id = ?", (learned_str, user_id,))
        await db.commit()

# --- Country Data (Arabic) ---

ARABIC_COUNTRIES_RAW = """
الترتيب | الدولة | العاصمة | القارة
1 | اليابان | طوكيو | آسيا
2 | روسيا | موسكو | آسيا
3 | كوريا الجنوبية | سيؤول | آسيا
4 | المكسيك | مكسيكو سيتي | أمريكا الشمالية
5 | إندونيسيا | جاكارتا | آسيا
6 | بيرو | ليما | أمريكا الجنوبية
7 | الصين | بكين | آسيا
8 | مصر | القاهرة | أفريقيا
9 | إيران | طهران | آسيا
10 | المملكة المتحدة | لندن | أوروبا
11 | كولومبيا | بوغوتا | أمريكا الجنوبية
12 | هونغ كونغ | هونغ كونغ | آسيا
13 | تايلاند | بانكوك | آسيا
14 | بنغلادش | دكا | آسيا
15 | العراق | بغداد | آسيا
16 | السعودية | الرياض | آسيا
17 | تشيلي | سانتياغو | أمريكا الجنوبية
18 | سنغافورة | سنغافورة | آسيا
19 | جمهورية الكونغو الديمقراطية | كينشاسا | أفريقيا
20 | تركيا | أنقرة | آسيا، وأفريقيا
21 | جنوب أفريقيا | كيب تاون التشريعية، بريتوريا الرسمية | أفريقيا
22 | ألمانيا | برلين | أوروبا
23 | فيتنام | هانوي | آسيا
24 | إسبانيا | مدريد | أوروبا
25 | كوريا الشمالية | بيونغ يانغ | آسيا
26 | أفغانستان | كابول | آسيا
27 | الأرجنتين | بيونس أيرس | أمريكا الجنوبية
28 | إثيوبيا | أديس أبابا | أفريقيا
29 | كينيا | نيروبي | أفريقيا
30 | تايوان | تايبيه | آسيا
31 | البرازيل | برازيليا | أمريكا الجنوبية
32 | أوكرانيا | كييف | أوروبا
33 | إيطاليا | روما | أوروبا
34 | أنغولا | لواندا | أفريقيا
35 | سوريا | دمشق | آسيا
36 | كوبا | هافانا | أمريكا الشمالية
37 | أوزبكستان | طشقند | آسيا
38 | فرنسا | باريس | أوروبا
39 | أذربيجان | باكو | أوروبا
40 | رومانيا | بوخاريست | أوروبا
41 | جمهورية الدومينيكان | سانتو دومينجو | أمريكا الشمالية
42 | فنزويلا | كاراكاس | أمريكا الجنوبية
43 | المغرب | الرباط | أفريقيا
44 | السودان | الخرطوم | أفريقيا
45 | جنوب السودان | جوبا | أفريقيا
46 | المجر | بودابست | أوروبا
47 | بولندا | وارسو | أوروبا
48 | روسيا البيضاء | منسك | أوروبا
49 | غانا | أكرا | أفريقيا
50 | الكاميرون | ياوندي | أفريقيا
51 | لبنان | بيروت | آسيا
52 | الفلبين | مانيلا | آسيا
53 | النمسا | فيينا | أوروبا
54 | الجزائر | الجزائر | أفريقيا
55 | الإكوادور | كيتو | أمريكا الجنوبية
56 | زيمبابوي | هراري | أفريقيا
57 | اليمن | صنعاء | آسيا
58 | غينيا | كوناكري | أفريقيا
59 | ماليزيا | كوالالامبور | آسيا
60 | الأوروغواي | مونتيفيديو | أمريكا الجنوبية
61 | زامبيا | لوساكا | أفريقيا
62 | مالي | باماكو | أفريقيا
63 | أوغندا | كمبالا | أفريقيا
64 | هايتي | بورت أو برنس | أمريكا الشمالية
65 | الأردن | عمان | آسيا
66 | ليبيا | طرابلس | أفريقيا
67 | الكويت | الكويت | آسيا
68 | التشيك | براغ | أوروبا
69 | صربيا | بلغراد | أوروبا
70 | الصومال | مقديشو | أفريقيا
71 | بلغاريا | صوفيا | أوروبا
72 | جمهورية الكونغو | برازافيل | أفريقيا
73 | بلجيكيا | بروكسل العاصمة | أوروبا
74 | أرمينيا | يريفان | آسيا
75 | موزمبيق | مابوتو | أفريقيا
76 | جورجيا | تبليسي | آسيا وأوروبا
77 | السنغال | داكار | أفريقيا
78 | بوركينا فاسو | واغادوغو | أفريقيا
79 | إيرلندا | دبلن | أوروبا
80 | غواتيمالا | غواتيمالا سيتي | أمريكا الشمالية
81 | ميانمار | نايبيداو | آسيا
82 | قيرغيزستان | بيشكيك | آسيا
83 | توغو | لومي | أفريقيا
84 | بنما | بنما سيتي | أمريكا الشمالية
85 | بوليفيا | لاباز | أمريكا الجنوبية
86 | نيبال | كاتماندو | آسيا
87 | سلطنة عُمان | مسقط | آسيا
88 | النيجر | نيامي | أفريقيا
89 | نيجيريا | أبوجا | أفريقيا
90 | السويد | ستوكهولم | أوروبا
91 | تونس | تونس | أفريقيا
92 | تركمانستان | عشق أباد | آسيا
93 | تشاد | نجامينا | أفريقيا
94 | فلسطين | القدس | آسيا
95 | هولندا | أمستردام | أوروبا
96 | جمهورية إفريقيا الوسطى | بانغي | أفريقيا
97 | كندا | أوتاوا | أمريكا الشمالية
98 | اليونان | أثينا | أوروبا
99 | موريتانيا | نواكشوط | أفريقيا
100 | رواندا | كيغالي | أفريقيا
101 | لاتفيا | ريغا | أوروبا
102 | سانت فينسنت والغرينادين | كينغستاون | أمريكا الشمالية
103 | كازاخستان | أستانا | آسيا وأوروبا
104 | كرواتيا | زغرب | أوروبا
105 | كمبوديا | بنوم بنه | آسيا
106 | مولدوفا | كيشيناو | أوروبا
107 | الولايات المتحدة الأمريكية | واشنطن العاصمة | أمريكا الشمالية
108 | الإمارات | أبو ظبي | آسيا
109 | طاجيكستان | دوشنبه | آسيا
110 | فنلندا | هلسنكي | أوروبا
111 | ليتوانيا | فيلنيوس | أوروبا
112 | الغابون | ليبرفيل | أفريقيا
113 | إريتريا | أسمرة | أفريقيا
114 | النرويج | أوسلو | أوروبا
115 | البرتغال | لشبونة | أوروبا
116 | السلفادور | سان سلفادور | أمريكا الشمالية
117 | باراغواي | أسونسيون | أمريكا الجنوبية
118 | ماكاو | ماكاو | آسيا
119 | ناورو | يارين | أوقيانوسيا
120 | مقدونيا الشمالية | سكوبيه | أوروبا
121 | الدنمارك | كوبنهاغن | أوروبا
122 | ساحل العاج | ياموسوكرو | أفريقيا
123 | غينيا بيساو | بيساو | أفريقيا
124 | سلوفاكيا | براتيسلافا | أوروبا
125 | إستونيا | تالين | أوروبا
126 | بوروندي | غيتيغا | أفريقيا
127 | البوسنة والهرسك | سراييفو | أوروبا
128 | نيوزيلندا | ويلينغتون | أوقيانوسيا
129 | ألبانيا | تيرانا | أوروبا
130 | أستراليا | كانبرا | أوقيانوسيا
131 | كوستاريكا | سان خوسيه | أمريكا الشمالية
132 | قطر | الدوحة | آسيا
133 | بابوا غينيا الجديدة | بورت مورسبي | أوقيانوسيا
134 | تنزانيا | دودوما | أفريقيا
135 | الهند | نيودلهي | آسيا
136 | لاوس | فيينتيان | آسيا
137 | قبرص | نيقوسيا | أوروبا
138 | ليسوتو | ماسيرو | أفريقيا
139 | سلوفينيا | ليوبليانا | أوروبا
140 | سورينام | باراماريبو | أمريكا الجنوبية
141 | ناميبيا | ويندهوك | أفريقيا
142 | بوتسوانا | غابورون | أفريقيا
143 | بنين | بورتو نوفو | أفريقيا
144 | بوليفيا | سوكري | أمريكا الجنوبية
145 | موريشيوس | بورت لويس | أفريقيا
146 | الجبل الأسود | بودغوريتشا | أوروبا
147 | البحرين | المنامة | آسيا
148 | غيانا | جورج تاون | أمريكا الجنوبية
149 | الرأس الأخضر | برايا | أفريقيا
150 | سويسرا | برن | أوروبا
151 | أيسلندا | ريكيافيك | أوروبا
152 | جزر المالديف | ماليه | آسيا
153 | بوتان | تيمفو | آسيا
154 | غينيا الاستوائية | مالابو | أفريقيا
155 | فيجي | سوفا | أوقيانوسيا
156 | إسواتيني | مبابان | أفريقيا
157 | لوكسمبورغ | لوكسمبورغ | أوروبا
158 | جزر القمر | موروني | أفريقيا
159 | تيمور الشرقية | ديلي | آسيا
160 | سانت لوسيا | كاستريس | أمريكا الشمالية
161 | ساو تومي وبرينسيبي | ساو تومي | أفريقيا
162 | ترينيداد وتوباغو | بورت أوف سبين | أمريكا الجنوبية
163 | ساموا | أبيا | أوقيانوسيا
164 | فانواتو | بورت فيلا | أوقيانوسيا
165 | موناكو | موناكو | أوروبا
166 | سيشل | فيكتوريا | أفريقيا
167 | بروناي | بندر سيري بيغاوان | آسيا
168 | أندورا | أندورا لا فيلا | أوروبا
169 | أنتيغوا وباربودا | سانت جونز | أمريكا الشمالية
170 | تونغا | نوكو ألوفا | أوقيانوسيا
171 | سانت كيتس ونيفيس | باستير | أمريكا الشمالية
172 | بليز | بلموبان | أمريكا الشمالية
173 | غرينادا | سانت جورجز | أمريكا الشمالية
174 | مالطا | فاليتا | أوروبا
175 | سان مارينو | سان مارينو | أوروبا
176 | توفالو | فونافوتي | أوقيانوسيا
177 | الفاتيكان | الفاتيكان | أوروبا
178 | باكستان | إسلام أباد | آسيا
179 | مالاوي | ليلونغوي | أفريقيا
180 | ليبيريا | مونروفيا | أفريقيا
181 | كوسوفو | بريشتينا | أوروبا
182 | كيريباتي | تاراوا | أوقيانوسيا
183 | الباهاماس | ناساو | أمريكا الشمالية
184 | باربادوس | بريدج تاون | أمريكا الشمالية
185 | جيبوتي | جيبوتي | أفريقيا
186 | دومينيكا | روسو | أمريكا الشمالية
187 | غامبيا | بانجول | أفريقيا
188 | هندوراس | تيغوسيغالبا | أمريكا الشمالية
189 | جزر مارشال | ماجورو | أوقيانوسيا
190 | ولايات ميكرونيسيا المتحدة | باليكير | أوقيانوسيا
191 | منغوليا | أولان باتور | آسيا
192 | نيكاراغوا | ماناغوا | أمريكا الشمالية
193 | بالاو | نغيرولمود | أوقيانوسيا
194 | سريلانكا | سري جاياواردنابورا كوتي | آسيا
195 | سيراليون | فريتاون | أفريقيا
196 | أندونيسيا | جاكرتا | آسيا
197 | فيتنام | هانوي | آسيا
198 | لاوس | فيينتيان | آسيا
199 | كمبوديا | بنوم بنه | آسيا
200 | ميانمار | نايبيداو | آسيا
201 | تايلاند | بانكوك | آسيا
202 | ماليزيا | كوالالمبور | آسيا
203 | سنغافورة | سنغافورة | آسيا
204 | الفلبين | مانيلا | آسيا
205 | بروناي | بندر سيري بيغاوان | آسيا
206 | تيمور الشرقية | ديلي | آسيا
207 | بابوا غينيا الجديدة | بورت مورسبي | أوقيانوسيا
208 | جزر سليمان | هونيارا | أوقيانوسيا
209 | فانواتو | بورت فيلا | أوقيانوسيا
210 | فيجي | سوفا | أوقيانوسيا
211 | تونغا | نوكو ألوفا | أوقيانوسيا
212 | ساموا | أبيا | أوقيانوسيا
213 | توفالو | فونافوتي | أوقيانوسيا
214 | كيريباتي | تاراوا | أوقيانوسيا
215 | ناورو | يارين | أوقيانوسيا
216 | جزر مارشال | ماجورو | أوقيانوسيا
217 | ولايات ميكرونيسيا المتحدة | باليكير | أوقيانوسيا
218 | بالاو | نغيرولمود | أوقيانوسيا
219 | نيوزيلندا | ويلينغتون | أوقيانوسيا
220 | أستراليا | كانبرا | أوقيانوسيا
221 | الجزائر | الجزائر | أفريقيا
222 | أنغولا | لواندا | أفريقيا
223 | بنين | بورتو نوفو | أفريقيا
224 | بوتسوانا | غابورون | أفريقيا
225 | بوركينا فاسو | واغادوغو | أفريقيا
226 | بوروندي | غيتيغا | أفريقيا
227 | الرأس الأخضر | برايا | أفريقيا
228 | الكاميرون | ياوندي | أفريقيا
229 | جمهورية إفريقيا الوسطى | بانغي | أفريقيا
230 | تشاد | نجامينا | أفريقيا
231 | جزر القمر | موروني | أفريقيا
232 | جمهورية الكونغو | برازافيل | أفريقيا
233 | جمهورية الكونغو الديمقراطية | كينشاسا | أفريقيا
234 | ساحل العاج | ياموسوكرو | أفريقيا
235 | جيبوتي | جيبوتي | أفريقيا
236 | مصر | القاهرة | أفريقيا
237 | غينيا الاستوائية | مالابو | أفريقيا
238 | إريتريا | أسمرة | أفريقيا
239 | إسواتيني | مبابان | أفريقيا
240 | إثيوبيا | أديس أبابا | أفريقيا
241 | الغابون | ليبرفيل | أفريقيا
242 | غامبيا | بانجول | أفريقيا
243 | غانا | أكرا | أفريقيا
244 | غينيا | كوناكري | أفريقيا
245 | غينيا بيساو | بيساو | أفريقيا
246 | كينيا | نيروبي | أفريقيا
247 | ليسوتو | ماسيرو | أفريقيا
248 | ليبيريا | مونروفيا | أفريقيا
249 | ليبيا | طرابلس | أفريقيا
250 | مدغشقر | أنتاناناريفو | أفريقيا
251 | مالاوي | ليلونغوي | أفريقيا
252 | مالي | باماكو | أفريقيا
253 | موريتانيا | نواكشوط | أفريقيا
254 | موريشيوس | بورت لويس | أفريقيا
255 | المغرب | الرباط | أفريقيا
256 | موزمبيق | مابوتو | أفريقيا
257 | ناميبيا | ويندهوك | أفريقيا
258 | النيجر | نيامي | أفريقيا
259 | نيجيريا | أبوجا | أفريقيا
260 | رواندا | كيغالي | أفريقيا
261 | ساو تومي وبرينسيبي | ساو تومي | أفريقيا
262 | السنغال | داكار | أفريقيا
263 | سيشل | فيكتوريا | أفريقيا
264 | سيراليون | فريتاون | أفريقيا
265 | الصومال | مقديشو | أفريقيا
266 | جنوب أفريقيا | بريتوريا | أفريقيا
267 | جنوب السودان | جوبا | أفريقيا
268 | السودان | الخرطوم | أفريقيا
269 | تنزانيا | دودوما | أفريقيا
270 | توغو | لومي | أفريقيا
271 | تونس | تونس | أفريقيا
272 | أوغندا | كمبالا | أفريقيا
273 | زامبيا | لوساكا | أفريقيا
274 | زيمبابوي | هراري | أفريقيا
275 | أفغانستان | كابول | آسيا
276 | أرمينيا | يريفان | آسيا
277 | أذربيجان | باكو | آسيا
278 | البحرين | المنامة | آسيا
279 | بنغلادش | دكا | آسيا
280 | بوتان | تيمفو | آسيا
281 | بروناي | بندر سيري بيغاوان | آسيا
282 | كمبوديا | بنوم بنه | آسيا
283 | الصين | بكين | آسيا
284 | قبرص | نيقوسيا | آسيا
285 | تيمور الشرقية | ديلي | آسيا
286 | الهند | نيودلهلي | آسيا
287 | إندونيسيا | جاكرتا | آسيا
288 | إيران | طهران | آسيا
289 | العراق | بغداد | آسيا
290 | إسرائيل | القدس | آسيا
291 | اليابان | طوكيو | آسيا
292 | الأردن | عمان | آسيا
293 | كازاخستان | أستانا | آسيا
294 | كوريا الشمالية | بيونغ يانغ | آسيا
295 | كوريا الجنوبية | سيؤول | آسيا
296 | الكويت | الكويت | آسيا
297 | قيرغيزستان | بيشكيك | آسيا
298 | لاوس | فيينتيان | آسيا
299 | لبنان | بيروت | آسيا
300 | ماليزيا | كوالالمبور | آسيا
301 | جزر المالديف | ماليه | آسيا
302 | منغوليا | أولان باتور | آسيا
303 | ميانمار | نايبيداو | آسيا
304 | نيبال | كاتماندو | آسيا
305 | سلطنة عُمان | مسقط | آسيا
306 | باكستان | إسلام أباد | آسيا
307 | فلسطين | القدس | آسيا
308 | الفلبين | مانيلا | آسيا
309 | قطر | الدوحة | آسيا
310 | السعودية | الرياض | آسيا
311 | سنغافورة | سنغافورة | آسيا
312 | سريلانكا | سري جاياواردنابورا كوتي | آسيا
313 | سوريا | دمشق | آسيا
314 | طاجيكستان | دوشنبه | آسيا
315 | تايلاند | بانكوك | آسيا
316 | تركيا | أنقرة | آسيا
317 | تركمانستان | عشق أباد | آسيا
318 | الإمارات | أبو ظبي | آسيا
319 | أوزبكستان | طشقند | آسيا
320 | فيتنام | هانوي | آسيا
321 | اليمن | صنعاء | آسيا
322 | ألبانيا | تيرانا | أوروبا
323 | أندورا | أندورا لا فيلا | أوروبا
324 | النمسا | فيينا | أوروبا
325 | روسيا البيضاء | منسك | أوروبا
326 | بلجيكا | بروكسل | أوروبا
327 | البوسنة والهرسك | سراييفو | أوروبا
328 | بلغاريا | صوفيا | أوروبا
329 | كرواتيا | زغرب | أوروبا
330 | التشيك | براغ | أوروبا
331 | الدنمارك | كوبنهاغن | أوروبا
332 | إستونيا | تالين | أوروبا
333 | فنلندا | هلسنكي | أوروبا
334 | فرنسا | باريس | أوروبا
335 | ألمانيا | برلين | أوروبا
336 | اليونان | أثينا | أوروبا
337 | المجر | بودابست | أوروبا
338 | أيسلندا | ريكيافيك | أوروبا
339 | إيرلندا | دبلن | أوروبا
340 | إيطاليا | روما | أوروبا
341 | كوسوفو | بريشتينا | أوروبا
342 | لاتفيا | ريغا | أوروبا
343 | ليختنشتاين | فادوتس | أوروبا
344 | ليتوانيا | فيلنيوس | أوروبا
345 | لوكسمبورغ | لوكسمبورغ | أوروبا
346 | مالطا | فاليتا | أوروبا
347 | مولدوفا | كيشيناو | أوروبا
348 | موناكو | موناكو | أوروبا
349 | الجبل الأسود | بودغوريتشا | أوروبا
350 | هولندا | أمستردام | أوروبا
351 | مقدونيا الشمالية | سكوبيه | أوروبا
352 | النرويج | أوسلو | أوروبا
353 | بولندا | وارسو | أوروبا
354 | البرتغال | لشبونة | أوروبا
355 | رومانيا | بوخاريست | أوروبا
356 | روسيا | موسكو | أوروبا
357 | سان مارينو | سان مارينو | أوروبا
358 | صربيا | بلغراد | أوروبا
359 | سلوفاكيا | براتيسلافا | أوروبا
360 | سلوفينيا | ليوبليانا | أوروبا
361 | إسبانيا | مدريد | أوروبا
362 | السويد | ستوكهولم | أوروبا
363 | سويسرا | برن | أوروبا
364 | أوكرانيا | كييف | أوروبا
365 | المملكة المتحدة | لندن | أوروبا
366 | الفاتيكان | الفاتيكان | أوروبا
367 | كندا | أوتاوا | أمريكا الشمالية
368 | كوستاريكا | سان خوسيه | أمريكا الشمالية
369 | كوبا | هافانا | أمريكا الشمالية
370 | دومينيكا | روسو | أمريكا الشمالية
371 | جمهورية الدومينيكان | سانتو دومينغو | أمريكا الشمالية
372 | السلفادور | سان سلفادور | أمريكا الشمالية
373 | غرينادا | سانت جورجز | أمريكا الشمالية
374 | غواتيمالا | غواتيمالا سيتي | أمريكا الشمالية
375 | هايتي | بورت أو برنس | أمريكا الشمالية
376 | هندوراس | تيغوسيغالبا | أمريكا الشمالية
377 | جامايكا | كينغستون | أمريكا الشمالية
378 | المكسيك | مكسيكو سيتي | أمريكا الشمالية
379 | نيكاراغوا | ماناغوا | أمريكا الشمالية
380 | بنما | بنما سيتي | أمريكا الشمالية
381 | سانت كيتس ونيفيس | باستير | أمريكا الشمالية
382 | سانت لوسيا | كاستريس | أمريكا الشمالية
383 | سانت فينسنت والغرينادين | كينغستاون | أمريكا الشمالية
384 | ترينيداد وتوباغو | بورت أوف سبين | أمريكا الشمالية
385 | الولايات المتحدة الأمريكية | واشنطن العاصمة | أمريكا الشمالية
386 | الأرجنتين | بوينس آيرس | أمريكا الجنوبية
387 | بوليفيا | لاباز | أمريكا الجنوبية
388 | البرازيل | برازيليا | أمريكا الجنوبية
389 | تشيلي | سانتياغو | أمريكا الجنوبية
390 | كولومبيا | بوغوتا | أمريكا الجنوبية
391 | الإكوادور | كيتو | أمريكا الجنوبية
392 | غيانا | جورج تاون | أمريكا الجنوبية
393 | باراغواي | أسونسيون | أمريكا الجنوبية
394 | بيرو | ليما | أمريكا الجنوبية
395 | سورينام | باراماريبو | أمريكا الجنوبية
396 | الأوروغواي | مونتيفيديو | أمريكا الجنوبية
397 | فنزويلا | كاراكاس | أمريكا الجنوبية
398 | أستراليا | كانبرا | أوقيانوسيا
399 | فيجي | سوفا | أوقيانوسيا
400 | كيريباتي | تاراوا | أوقيانوسيا
401 | جزر مارشال | ماجورو | أوقيانوسيا
402 | ولايات ميكرونيسيا المتحدة | باليكير | أوقيانوسيا
403 | ناورو | يارين | أوقيانوسيا
404 | نيوزيلندا | ويلينغتون | أوقيانوسيا
405 | بالاو | نغيرولمود | أوقيانوسيا
406 | بابوا غينيا الجديدة | بورت مورسبي | أوقيانوسيا
407 | ساموا | أبيا | أوقيانوسيا
408 | جزر سليمان | هونيارا | أوقيانوسيا
409 | تونغا | نوكو ألوفا | أوقيانوسيا
410 | توفالو | فونافوتي | أوقيانوسيا
411 | فانواتو | بورت فيلا | أوقيانوسيا
"""

COUNTRIES_DATA_ARABIC = []

def load_countries_data():
    global COUNTRIES_DATA_ARABIC
    lines = ARABIC_COUNTRIES_RAW.strip().split("\n")
    for line in lines[1:]:
        parts = line.split(" | ")
        if len(parts) >= 3:
            country = parts[1].strip()
            capital = parts[2].strip()
            continent = parts[3].strip() if len(parts) > 3 else "غير محدد"

            variations = []
            # Add common variations for Arabic capitals, especially for 'ة' and 'ه'
            # and other common Arabic character normalizations
            normalized_capital = capital.replace('ة', 'ه').replace('أ', 'ا').replace('إ', 'ا').replace('آ', 'ا').replace('ى', 'ي')
            variations.append(normalized_capital)
            if 'ة' in capital: # Handle cases where 'ة' might be replaced by 'ه'
                variations.append(capital.replace('ة', 'ه'))
            if 'ه' in capital: # Handle cases where 'ه' might be replaced by 'ة'
                variations.append(capital.replace('ه', 'ة'))

            # Add English variations for common capitals if known, for better matching
            # This part can be expanded with more specific variations as needed
            # A more robust solution would involve a separate mapping for English names.
            english_variations = {
                "القدس": ["jerusalem"],
                "واشنطن العاصمة": ["washington dc", "washington"],
                "لندن": ["london"],
                "باريس": ["paris"],
                "روما": ["rome"],
                "بكين": ["beijing", "peking"],
                "موسكو": ["moscow"],
                "نيودلهي": ["new delhi"],
                "طوكيو": ["tokyo"],
                "القاهرة": ["cairo"],
                "الرياض": ["riyadh"],
                "أنقرة": ["ankara"],
                "دمشق": ["damascus"],
                "أبو ظبي": ["abu dhabi"],
                "المنامة": ["manama"],
                "مسقط": ["muscat"],
                "الكويت": ["kuwait city"],
                "الدوحة": ["doha"],
                "بيروت": ["beirut"],
                "عمان": ["amman"],
                "بغداد": ["baghdad"],
                "الخرطوم": ["khartoum"],
                "طرابلس": ["tripoli"],
                "تونس": ["tunis"],
                "الرباط": ["rabat"],
                "الجزائر": ["algiers"],
                "مقديشو": ["mogadishu"],
                "نيروبي": ["nairobi"],
                "أديس أبابا": ["addis ababa"],
                "برلين": ["berlin"],
                "مدريد": ["madrid"],
                "ستوكهولم": ["stockholm"],
                "أوسلو": ["oslo"],
                "هلسنكي": ["helsinki"],
                "لشبونة": ["lisbon"],
                "دبلن": ["dublin"],
                "فيينا": ["vienna"],
                "بروكسل": ["brussels"],
                "برن": ["bern"],
                "كوبنهاغن": ["copenhagen"],
                "وارسو": ["warsaw"],
                "كييف": ["kiev", "kyiv"],
                "برازيليا": ["brasilia"],
                "بوينس آيرس": ["buenos aires"],
                "مكسيكو سيتي": ["mexico city"],
                "أوتاوا": ["ottawa"],
                "كانبرا": ["canberra"],
                "ويلينغتون": ["wellington"],
                "جاكرتا": ["jakarta"],
                "مانيلا": ["manila"],
                "كوالالمبور": ["kuala lumpur"],
                "سنغافورة": ["singapore"],
                "بانكوك": ["bangkok"],
                "هانوي": ["hanoi"],
                "ليما": ["lima"],
                "سانتياغو": ["santiago"],
                "بوغوتا": ["bogota"],
                "كاراكاس": ["caracas"],
                "راباط": ["rabat"],
                "الجزائر": ["algiers"],
                "تونس": ["tunis"],
                "نيروبي": ["nairobi"],
                "أبوجا": ["abuja"],
                "أكرا": ["accra"],
                "طهران": ["tehran"],
                "بغداد": ["baghdad"],
                "القدس الشريف": ["jerusalem"],
                "بيروت": ["beirut"],
                "عمان": ["amman"],
                "الدوحة": ["doha"],
                "الكويت": ["kuwait city"],
                "مسقط": ["muscat"],
                "المنامة": ["manama"],
                "أبو ظبي": ["abu dhabi"],
                "مقديشو": ["mogadishu"],
                "برازافيل": ["brazzaville"],
                "بانغي": ["bangui"],
                "جيبوتي": ["djibouti city"],
                "أسمرة": ["asmara"],
                "مبابان": ["mbabane"],
                "ليبرفيل": ["libreville"],
                "بانجول": ["banjul"],
                "بيساو": ["bissau"],
                "ماسيرو": ["maseru"],
                "مونروفيا": ["monrovia"],
                "نواكشوط": ["nouakchott"],
                "نيامي": ["niamey"],
                "ساو تومي": ["sao tome"],
                "فريتاون": ["freetown"],
                "جوبا": ["juba"],
                "لومي": ["lome"],
                "موروني": ["moroni"],
                "بورت فيلا": ["port vila"],
                "أبيا": ["apia"],
                "نوكو ألوفا": ["nukualofa"],
                "سوفا": ["suva"],
                "باليكير": ["palikir"],
                "ماجورو": ["majuro"],
                "تاراوا": ["tarawa atoll"],
                "فونافوتي": ["funafuti"],
                "يارين": ["yaren"],
                "سان مارينو": ["san marino"],
                "فادوتس": ["vaduz"],
                "واغادوغو": ["ouagadougou"],
                "بورت أو برنس": ["port-au-prince"],
                "بلموبان": ["belmopan"],
                "سانت جونز": ["saint john's"],
                "بريدج تاون": ["bridgetown"],
                "كاستريس": ["castries"],
                "سانت جورجز": ["saint george's"],
                "باستير": ["basseterre"],
                "روسو": ["roseau"],
                "تيغوسيغالبا": ["tegucigalpa"],
                "ماناغوا": ["managua"],
                "نغيرولمود": ["melekeok"],
                "كولمبو": ["colombo"],
                "فريتاون": ["freetown"],
                "بورتو نوفو": ["porto-novo"],
                "غابورون": ["gaborone"],
                "ويندهوك": ["windhoek"],
                "بورت لويس": ["port louis"],
                "ليونغوي": ["lilongwe"],
                "مونروفيا": ["monrovia"],
                "بريشتينا": ["pristina"],
                "أولان باتور": ["ulan bator"],
                "نيقوسيا": ["nicosia"],
                "فاليتا": ["valletta"],
                "تيمفو": ["thimphu"],
                "مالابو": ["malabo"],
                "ديلي": ["dili"],
                "أندورا لا فيلا": ["andorra la vella"],
                "بندر سيري بيغاوان": ["bandar seri begawan"],
                "موناكو": ["monaco"],
                "فيكتوريا": ["victoria"],
                "أبيا": ["apia"],
                "بورت فيلا": ["port vila"],
                "نوكو ألوفا": ["nukualofa"],
                "سوفا": ["suva"],
                "مبابان": ["mbabane"],
                "لوكسمبورغ": ["luxembourg"],
                "موروني": ["moroni"],
                "ديلي": ["dili"],
                "كاستريس": ["castries"],
                "ساو تومي": ["sao tome"],
                "بورت أوف سبين": ["port of spain"],
                "أبيا": ["apia"],
                "بورت فيلا": ["port vila"],
                "موناكو": ["monaco"],
                "فيكتوريا": ["victoria"],
                "بندر سيري بيغاوان": ["bandar seri begawan"],
                "أندورا لا فيلا": ["andorra la vella"],
                "سانت جونز": ["saint john's"],
                "نوكو ألوفا": ["nukualofa"],
                "باستير": ["basseterre"],
                "بلموبان": ["belmopan"],
                "سانت جورجز": ["saint george's"],
                "فاليتا": ["valletta"],
                "سان مارينو": ["san marino"],
                "فونافوتي": ["funafuti"],
                "الفاتيكان": ["vatican city"],
                "إسلام أباد": ["islamabad"],
                "بورت لويس": ["port louis"],
                "ليونغوي": ["lilongwe"],
                "مونروفيا": ["monrovia"],
                "بريشتينا": ["pristina"],
                "تاراوا": ["tarawa atoll"],
                "ناساو": ["nassau"],
                "بريدج تاون": ["bridgetown"],
                "جيبوتي": ["djibouti"],
                "روسو": ["roseau"],
                "بانجول": ["banjul"],
                "تيغوسيغالبا": ["tegucigalpa"],
                "ماجورو": ["majuro"],
                "باليكير": ["palikir"],
                "أولان باتور": ["ulan bator"],
                "ماناغوا": ["managua"],
                "نغيرولمود": ["melekeok"],
                "كولمبو": ["colombo"],
                "فريتاون": ["freetown"],
                "سري جاياواردنابورا كوتي": ["sri jayawardenepura kotte"]
            }
            if capital in english_variations:
                variations.extend(english_variations[capital])

            COUNTRIES_DATA_ARABIC.append({"country": country, "capital": capital, "variations": list(set(variations)), "continent": continent})

# Call load_countries_data to populate the list
load_countries_data()

# Assign levels based on a simple heuristic for now. This can be refined later.
# Easy: First 60 countries
# Medium: Next 60 countries
# Hard: Remaining countries

all_countries_shuffled = random.sample(COUNTRIES_DATA_ARABIC, len(COUNTRIES_DATA_ARABIC))

COUNTRIES_BY_LEVEL_ARABIC = {
    "easy": all_countries_shuffled[0:60],
    "medium": all_countries_shuffled[60:120],
    "hard": all_countries_shuffled[120:]
}

# --- Helper Functions ---

def normalize_answer(answer: str) -> str:
    # Normalize Arabic characters and convert to lowercase for robust comparison
    answer = answer.strip().lower()
    answer = answer.replace('ة', 'ه')
    answer = answer.replace('أ', 'ا')
    answer = answer.replace('إ', 'ا')
    answer = answer.replace('آ', 'ا')
    answer = answer.replace('ى', 'ي')
    # Remove non-alphanumeric characters (keeping spaces)
    answer = re.sub(r'[^\w\s]', '', answer)
    return answer

def check_answer(user_answer: str, correct_capital: str, variations: list[str]) -> bool:
    normalized_user_answer = normalize_answer(user_answer)
    
    # Check against the correct capital first
    if normalized_user_answer == normalize_answer(correct_capital):
        return True

    # Check against all variations
    for var in variations:
        if normalized_user_answer == normalize_answer(var):
            return True
    return False

# --- FSM States ---

class QuizState(StatesGroup):
    waiting_for_answer = State()
    browsing_capitals = State()

# --- Keyboards ---

main_menu_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="/easy"), KeyboardButton(text="/medium"), KeyboardButton(text="/hard")],
        [KeyboardButton(text="/stats"), KeyboardButton(text="/reset")],
        [KeyboardButton(text="/browse")]
    ],
    resize_keyboard=True,
    one_time_keyboard=False
)

browse_menu_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="التالي"), KeyboardButton(text="تعلمت هذا")],
        [KeyboardButton(text="العودة للقائمة الرئيسية")]
    ],
    resize_keyboard=True,
    one_time_keyboard=False
)

# --- Handlers ---

router = Router()

@router.message(CommandStart())
async def command_start_handler(message: Message, state: FSMContext) -> None:
    user_id = message.from_user.id
    await create_user(user_id)
    await state.clear()
    await message.answer(
        f"مرحباً بك في بوت تدريب عواصم العالم يا {message.from_user.full_name}!\n"\
        "اختر مستوى الصعوبة لبدء الاختبار، أو تصفح العواصم.",
        reply_markup=main_menu_keyboard
    )

@router.message(Command("easy"))
@router.message(Command("medium"))
@router.message(Command("hard"))
async def start_quiz_handler(message: Message, state: FSMContext) -> None:
    level = message.text[1:]  # Remove '/' from command
    user_id = message.from_user.id
    user_data = await get_user(user_id)
    learned_capitals = user_data.get("learned_capitals", [])

    available_countries = [c for c in COUNTRIES_BY_LEVEL_ARABIC[level] if c["capital"] not in learned_capitals]

    if not available_countries:
        await message.answer(f"لا توجد عواصم متاحة في مستوى {level} لم تتعلمها بعد. يمكنك إعادة تعيين إحصائياتك أو تجربة مستوى آخر.", reply_markup=main_menu_keyboard)
        await state.clear()
        return

    country_data = random.choice(available_countries)
    await state.update_data(current_country=country_data["country"], correct_capital=country_data["capital"], level=level, variations=country_data["variations"])
    await state.set_state(QuizState.waiting_for_answer)
    await message.answer(f"ما هي عاصمة {country_data['country']}؟", reply_markup=types.ReplyKeyboardRemove())

@router.message(QuizState.waiting_for_answer)
async def process_answer(message: Message, state: FSMContext) -> None:
    user_id = message.from_user.id
    state_data = await state.get_data()
    current_country = state_data.get("current_country")
    correct_capital = state_data.get("correct_capital")
    level = state_data.get("level")
    variations = state_data.get("variations", [])
    user_answer = message.text

    if not current_country or not correct_capital or not level:
        await message.answer("حدث خطأ. يرجى بدء اختبار جديد باستخدام /easy, /medium, أو /hard.", reply_markup=main_menu_keyboard)
        await state.clear()
        return

    is_correct = check_answer(user_answer, correct_capital, variations)

    if is_correct:
        feedback = "✅ إجابة صحيحة!"
    else:
        feedback = f"❌ إجابة خاطئة. العاصمة الصحيحة هي {correct_capital}."

    await add_history_entry(user_id, current_country, user_answer, correct_capital, is_correct, level)
    await update_user_stats(user_id, is_correct)
    await message.answer(feedback)

    # Automatically send next question
    user_data = await get_user(user_id)
    learned_capitals = user_data.get("learned_capitals", [])
    available_countries = [c for c in COUNTRIES_BY_LEVEL_ARABIC[level] if c["capital"] not in learned_capitals]

    if not available_countries:
        await message.answer(f"لقد أكملت جميع العواصم في مستوى {level} التي لم تتعلمها بعد! يمكنك إعادة تعيين إحصائياتك أو تجربة مستوى آخر.", reply_markup=main_menu_keyboard)
        await state.clear()
        return

    country_data = random.choice(available_countries)
    await state.update_data(current_country=country_data["country"], correct_capital=country_data["capital"], level=level, variations=country_data["variations"])
    await message.answer(f"ما هي عاصمة {country_data['country']}؟")

@router.message(Command("stats"))
async def show_stats_handler(message: Message, state: FSMContext) -> None:
    user_id = message.from_user.id
    user_data = await get_user(user_id)

    if not user_data:
        await message.answer("لم يتم تسجيلك بعد. يرجى استخدام /start.", reply_markup=main_menu_keyboard)
        return

    total_questions = user_data["total_questions"]
    correct_answers = user_data["correct_answers"]
    accuracy = (correct_answers / total_questions * 100) if total_questions > 0 else 0

    stats_message = f"إحصائياتك يا {message.from_user.full_name}:\n"
    stats_message += f"- إجمالي الأسئلة: {total_questions}\n"
    stats_message += f"- الإجابات الصحيحة: {correct_answers}\n"
    stats_message += f"- الدقة: {accuracy:.2f}%\n\n"

    history = await get_user_history(user_id, 10)
    if history:
        stats_message += "آخر 10 إجابات:\n"
        for entry in history:
            country, user_ans, correct_ans, is_corr, timestamp = entry
            status = "✅" if is_corr else "❌"
            stats_message += f"  {status} {country}: إجابتك '{user_ans}', الصحيح '{correct_ans}' ({timestamp})\n"
    else:
        stats_message += "لا توجد سجلات اختبار بعد.\n"

    wrong_countries = await get_wrong_answers_count(user_id)
    if wrong_countries:
        stats_message += "\nالدول التي أخطأت فيها أكثر من مرة (أكثر 5):\n"
        for country, count in wrong_countries:
            stats_message += f"  - {country}: {count} مرات\n"

    await message.answer(stats_message, reply_markup=main_menu_keyboard)
    await state.clear()

@router.message(Command("reset"))
async def reset_stats_handler(message: Message, state: FSMContext) -> None:
    user_id = message.from_user.id
    await reset_user_stats(user_id)
    await state.clear()
    await message.answer("تمت إعادة تعيين إحصائياتك بنجاح!", reply_markup=main_menu_keyboard)

@router.message(Command("browse"))
async def browse_capitals_handler(message: Message, state: FSMContext) -> None:
    user_id = message.from_user.id
    user_data = await get_user(user_id)
    learned_capitals = user_data.get("learned_capitals", [])

    all_capitals_info = sorted(COUNTRIES_DATA_ARABIC, key=lambda x: x['capital'])
    unlearned_capitals_info = [c for c in all_capitals_info if c["capital"] not in learned_capitals]

    if not unlearned_capitals_info:
        await message.answer("لقد تعلمت جميع العواصم! تهانينا!", reply_markup=main_menu_keyboard)
        await state.clear()
        return

    await state.update_data(browse_index=0, browse_list=unlearned_capitals_info)
    await state.set_state(QuizState.browsing_capitals)

    current_entry = unlearned_capitals_info[0]
    await message.answer(f"تصفح العواصم:\n\nالدولة: {current_entry['country']}\nالعاصمة: {current_entry['capital']}", reply_markup=browse_menu_keyboard)

@router.message(QuizState.browsing_capitals, F.text == "التالي")
async def next_capital_handler(message: Message, state: FSMContext) -> None:
    state_data = await state.get_data()
    browse_list = state_data.get("browse_list", [])
    browse_index = state_data.get("browse_index", 0)

    if not browse_list:
        await message.answer("لا توجد عواصم للتصفح.", reply_markup=main_menu_keyboard)
        await state.clear()
        return

    browse_index = (browse_index + 1) % len(browse_list)
    await state.update_data(browse_index=browse_index)

    current_entry = browse_list[browse_index]
    await message.answer(f"تصفح العواصم:\n\nالدولة: {current_entry['country']}\nالعاصمة: {current_entry['capital']}", reply_markup=browse_menu_keyboard)

@router.message(QuizState.browsing_capitals, F.text == "تعلمت هذا")
async def mark_learned_handler(message: Message, state: FSMContext) -> None:
    user_id = message.from_user.id
    state_data = await state.get_data()
    browse_list = state_data.get("browse_list", [])
    browse_index = state_data.get("browse_index", 0)

    if not browse_list:
        await message.answer("لا توجد عواصم للتحديد كـ 'متعلمة'.", reply_markup=main_menu_keyboard)
        await state.clear()
        return

    current_capital_obj = browse_list[browse_index]
    current_capital_name = current_capital_obj["capital"]
    
    user_data = await get_user(user_id)
    learned_capitals = user_data.get("learned_capitals", [])

    if current_capital_name not in learned_capitals:
        learned_capitals.append(current_capital_name)
        await update_learned_capitals(user_id, learned_capitals)
        await message.answer(f"تم وضع '{current_capital_name}' كعاصمة متعلمة. لن تظهر في الاختبارات بعد الآن.")
    else:
        await message.answer(f"'{current_capital_name}' محددة بالفعل كعاصمة متعلمة.")

    # Update browse list to reflect learned capitals
    new_browse_list = [c for c in COUNTRIES_DATA_ARABIC if c["capital"] not in learned_capitals]
    new_browse_list = sorted(new_browse_list, key=lambda x: x['capital'])

    if not new_browse_list:
        await message.answer("لقد تعلمت جميع العواصم! تهانينا!", reply_markup=main_menu_keyboard)
        await state.clear()
        return

    # Adjust index if current capital was removed or list changed size
    if browse_index >= len(new_browse_list):
        browse_index = 0

    await state.update_data(browse_list=new_browse_list, browse_index=browse_index)

    next_entry = new_browse_list[browse_index]
    await message.answer(f"تصفح العواصم:\n\nالدولة: {next_entry['country']}\nالعاصمة: {next_entry['capital']}", reply_markup=browse_menu_keyboard)

@router.message(QuizState.browsing_capitals, F.text == "العودة للقائمة الرئيسية")
async def exit_browse_mode_handler(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("العودة إلى القائمة الرئيسية.", reply_markup=main_menu_keyboard)

@router.message()
async def echo_handler(message: Message, state: FSMContext) -> None:
    current_state = await state.get_state()
    if current_state == QuizState.waiting_for_answer:
        # If in quiz state, process as an answer, don't echo
        await process_answer(message, state)
    elif current_state == QuizState.browsing_capitals:
        # If in browsing state, ignore unexpected messages
        await message.answer("يرجى استخدام الأزرار للتنقل أو العودة للقائمة الرئيسية.", reply_markup=browse_menu_keyboard)
    else:
        await message.answer("أنا بوت تدريب عواصم العالم. يرجى استخدام الأوامر من القائمة الرئيسية.", reply_markup=main_menu_keyboard)

# --- Main function ---

async def main() -> None:
    await init_db()
    dp = Dispatcher()
    dp.include_router(router)

    # Initialize Bot with DefaultBotProperties
    bot = Bot(token=TELEGRAM_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))

    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
