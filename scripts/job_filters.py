"""
Cheap checks that decide which postings are worth a closer look, run on the
job lists we already downloaded (no extra requests):

  location_class()  "us" | "unclear" | "non-us"   (runs first)
  title_class()     "clear" | "ambiguous" | "drop"

"clear" titles say early career outright (New Grad, 2027, Engineer I, …);
"ambiguous" ones ("Software Engineer, Backend") need the description check.
The seniority score is based on the job-board-aggregator's _TIER_PATTERNS
(MIT license), with early-career words added and "tech" dropped.
"""

from __future__ import annotations

import re

# ── Location ─────────────────────────────────────────────────────────

_STATE_NAMES = (
    "alabama|alaska|arizona|arkansas|california|colorado|connecticut|delaware|florida|georgia|hawaii|"
    "idaho|illinois|indiana|iowa|kansas|kentucky|louisiana|maine|maryland|massachusetts|michigan|"
    "minnesota|mississippi|missouri|montana|nebraska|nevada|new hampshire|new jersey|new mexico|"
    "new york|north carolina|north dakota|ohio|oklahoma|oregon|pennsylvania|rhode island|"
    "south carolina|south dakota|tennessee|texas|utah|vermont|virginia|washington|west virginia|"
    "wisconsin|wyoming|district of columbia"
)
_STATE_ABBR = (
    "AL|AK|AZ|AR|CA|CO|CT|DE|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|MT|NE|NV|NH|NJ|"
    "NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY|DC"
)
_US_CITIES = (
    "san francisco|bay area|palo alto|mountain view|sunnyvale|san jose|santa clara|menlo park|"
    "redwood city|foster city|san mateo|oakland|berkeley|los angeles|santa monica|irvine|san diego|"
    "seattle|bellevue|redmond|kirkland|new york|nyc|brooklyn|boston|austin|dallas|houston|chicago|"
    "denver|boulder|atlanta|miami|raleigh|durham|pittsburgh|philadelphia|salt lake city|lehi|phoenix|"
    "scottsdale|minneapolis|detroit|ann arbor|columbus|nashville|reston|mclean|arlington"
)
# Uppercase country codes and "US-CA"-style prefixes are matched case-sensitively
_US_CODES = re.compile(r"\bUSA?\b|\bU\.S\.(A\.)?|\(US\)")
_US_WORDS = re.compile(rf"united states|\bamerica\b|\b({_STATE_NAMES})\b|\b({_US_CITIES})\b", re.I)
# State abbreviations only after a comma, "US-", or " - ", so IN/DE/OR can't match India, Madrid, "Hanoi OR…"
_US_ABBR = re.compile(rf"(?:,|\bUS[-,]|\s-)\s*({_STATE_ABBR})\b")
_NON_US = re.compile(
    r"\b(canada|toronto|vancouver|montreal|ottawa|waterloo|calgary|mexico|brazil|s[aã]o paulo|argentina|"
    r"buenos aires|colombia|bogot[aá]|chile|peru|uk|united kingdom|england|london|manchester|edinburgh|"
    r"scotland|ireland|dublin|germany|berlin|munich|hamburg|france|paris|spain|madrid|barcelona|portugal|"
    r"lisbon|italy|milan|netherlands|amsterdam|belgium|brussels|switzerland|zurich|z[uü]rich|geneva|"
    r"austria|vienna|sweden|stockholm|norway|oslo|denmark|copenhagen|finland|helsinki|poland|warsaw|"
    r"krak[oó]w|czech|prague|hungary|budapest|romania|bucharest|greece|athens|turkey|istanbul|ukraine|"
    r"kyiv|serbia|belgrade|israel|tel aviv|uae|dubai|abu dhabi|saudi|riyadh|qatar|egypt|cairo|nigeria|"
    r"lagos|kenya|nairobi|south africa|cape town|johannesburg|india|bangalore|bengaluru|hyderabad|pune|"
    r"mumbai|delhi|gurgaon|gurugram|noida|chennai|singapore|malaysia|kuala lumpur|indonesia|jakarta|"
    r"philippines|manila|vietnam|hanoi|ho chi minh|thailand|bangkok|china|beijing|shanghai|shenzhen|"
    r"hong kong|taiwan|taipei|japan|tokyo|korea|seoul|australia|sydney|melbourne|new zealand|auckland|"
    r"emea|apac|latam|europe|asia|africa|"
    # more cities, so European and other postings don't slip through as "unclear"
    r"d[uü]sseldorf|frankfurt|cologne|k[oö]ln|stuttgart|leipzig|dresden|nuremberg|n[uü]rnberg|lyon|"
    r"marseille|toulouse|rotterdam|the hague|utrecht|eindhoven|antwerp|ghent|luxembourg|bern|basel|"
    r"lausanne|valencia|seville|bilbao|porto|turin|rome|naples|bologna|florence|gothenburg|malm[oö]|"
    r"aarhus|tallinn|riga|vilnius|sofia|zagreb|ljubljana|bratislava|wroc[lł]aw|gda[nń]sk|pozna[nń]|cluj|"
    r"brno|belfast|glasgow|bristol|oxford|leeds|birmingham, uk|cork|galway|limerick|montr[eé]al|quebec|"
    r"halifax|winnipeg|edmonton|mississauga|kitchener|guadalajara|monterrey|mexico city|cdmx|santiago|"
    r"lima|medell[ií]n|montevideo|curitiba|belo horizonte|porto alegre|florian[oó]polis|accra|kigali|"
    r"casablanca|amman|beirut|doha|karachi|lahore|islamabad|dhaka|colombo|ahmedabad|kolkata|kochi|"
    r"chandigarh|indore|coimbatore|da nang|cebu|makati|taguig|penang|bandung|osaka|kyoto|fukuoka|busan|"
    r"hsinchu|guangzhou|hangzhou|chengdu|nanjing|suzhou|brisbane|perth|adelaide|canberra|wellington|"
    r"deutschland|espa[nñ]a|italia|nederland|polska|[oö]sterreich|schweiz|suisse|belgique|danmark|"
    r"sverige|norge|suomi|t[uü]rkiye)\b",
    re.I,
)
# German-language postings mark gender this way: "(m/w/d)", "(w/m/d)", "(f/m/d)"
_EU_GENDER_MARK = re.compile(r"\((?:[mwfd]\s*/\s*){2}[mwfdx]\)", re.I)
_US_COUNTRY_VALUES = {"us", "usa", "united states", "united states of america"}


def _is_us(text: str) -> bool:
    if _US_CODES.search(text) or _US_WORDS.search(text):
        return True
    # A bare state abbreviation doesn't win over a named non-US place ("Hyderabad - TS - IN")
    return bool(_US_ABBR.search(text)) and not _NON_US.search(text)


def location_class(locations: list[str], countries: list[str] | None = None, title: str = "") -> str:
    """US or remote-US → "us"; only non-US places → "non-us"; otherwise "unclear".

    "unclear" covers "Remote" with no country, blank, and Workday's "2 Locations";
    those are kept and the description check decides.
    """
    countries = [c.strip() for c in (countries or []) if c and c.strip()]
    if any(c.lower() in _US_COUNTRY_VALUES for c in countries):
        return "us"
    texts = [t.strip() for t in locations if t and t.strip()]
    if any(_is_us(t) for t in texts):
        return "us"
    if _EU_GENDER_MARK.search(title or ""):
        return "non-us"
    if countries:  # structured country fields beat free text
        return "non-us"
    if texts and all(_NON_US.search(t) for t in texts):
        return "non-us"
    return "unclear"


# ── Title ────────────────────────────────────────────────────────────

_ENG = re.compile(r"\b(engineers?|developers?|scientists?|swe|sde|programmer)\b", re.I)
_ENGINEERING = re.compile(r"\bengineering\b", re.I)  # "Software Engineering, New Grad"
_STRONG = re.compile(
    r"\b(software|swe|sde|machine learning|ml|ai|artificial intelligence|deep learning|llm|genai|"
    r"full[- ]?stack|back[- ]?end|front[- ]?end|developer|programmer)\b",
    re.I,
)
_ROLE = re.compile(
    r"\b(software|swe|sde|machine learning|ml|ai|artificial intelligence|deep learning|computer vision|"
    r"nlp|llm|genai|generative|agents?|agentic|full[- ]?stack|back[- ]?end|front[- ]?end|web|mobile|ios|"
    r"android|platform|infrastructure|cloud|devops|reliability|sre|data|applied|research|"
    r"forward[- ]deployed|product engineer|developers?|programmer)\b",
    re.I,
)
# Engineering jobs that aren't software, unless the title also says software/ML/AI
_NOT_SOFTWARE = re.compile(
    r"\b(mechanical|electrical|civil|chemical|manufacturing|propulsion|structural|hardware|rf|analog|"
    r"asic|fpga|process|field|facilities|environmental|safety|quality|sales|technician|recruit\w*|"
    r"design verification|test technician|construction|biomedical|"
    # lab sciences: "Research Scientist, Purification Sciences" is biotech, not ML
    r"chemist|chemistry|biolog\w*|clinical|assay|purification|formulation|materials|pharmac\w*|"
    r"toxicolog\w*|immunolog\w*|genomics?|proteomics?|microbiolog\w*|biochem\w*|neuroscien\w*|laboratory)\b",
    re.I,
)

# (pattern, weight): positive = more senior, negative = earlier career
_TIERS = [(re.compile(p, re.I), w) for p, w in [
    (r"\b(chief|cto|vp|vice president|director)\b", 50),
    (r"\b(principal|distinguished|fellow|fellowship)\b", 40),
    (r"\b(staff|lead|head of)\b", 30),
    (r"\b(senior|sr\.?)\b", 20),
    (r"\b(architect|manager)\b", 15),
    (r"\bmid[\s-]?(level|senior)?\b", 15),
    (r"\b(iii|iv|v|vi)\b", 15),
    (r"\blevel\s*[4-9]\b", 15),
    (r"\b(engineer|engr)\s*[3-6]\b", 15),
    (r"\b(ii|2)\b", 5),
    (r"\blevel\s*3\b", 5),
    (r"\bassociate\b", -10),
    (r"\bassistant\b", -10),
    (r"\b(junior|jr\.?)\b", -20),
    (r"\bentry[\s-]?level\b", -25),
    (r"\b(i|1)\b(?!\d)", -15),
    (r"\b(trainee|graduates?|new[\s-]*grad(uate)?s?|recent[\s-]*grad(uate)?s?)\b", -25),
    (r"\bearly[\s-]?career\b", -25),
    (r"\b(university|college|campus)\b", -20),
    (r"\b20(26|27)\b", -20),
    (r"\b(rotational|apprentice(ship)?|residency program|pathways? program)\b", -20),
]]
# Only these words make a title an internship. Stacked entry signals ("Engineer 1 - Early Career - 2027") don't.
_INTERN = re.compile(r"\b(interns?|internships?|co-?ops?|coops?)\b", re.I)


# QA roles, dropped even when the title also says "software" (the user's choice).
# Titles that only mention "test" ("Software Engineer, Test Infrastructure") are kept.
_QA = re.compile(r"\bqa\b|quality assurance|\bquality engineer|software quality|\bsdet\b|\bengineer in test\b", re.I)
# Robotics roles, also the user's choice
_ROBOTICS = re.compile(r"\brobot(s|ic|ics)?\b", re.I)

_BUSINESS = re.compile(r"\bbusiness develop\w*|\bsales develop\w*|\bdeveloper relations\b|\bdevrel\b", re.I)

# Recruiting platforms that repost other companies' jobs. Add "site:board" names here.
SKIP_BOARDS = {"lever:jobgether", "ashby:clera"}

# The owner's hard rules by company: TikTok/ByteDance allow two applications at a time and both are
# used, so those are skipped; Amazon jobs are flagged for account and referral checks before applying.
SKIP_COMPANIES = re.compile(r"\b(tik\s?tok|byte\s?dance)\b", re.I)
AMAZON = re.compile(r"\b(amazon|aws|audible)\b", re.I)


def _words(title: str) -> str:
    """Treat underscores and slashes as spaces: "Co-op_Fall 2026" must read as "Co-op Fall 2026"."""
    return " ".join(re.sub(r"[_/|]+", " ", str(title or "")).split())


def seniority(title: str) -> str:
    title = _words(title)
    if _INTERN.search(title):
        return "intern"
    score = sum(w for p, w in _TIERS if p.search(title))
    if score <= -5:
        return "entry"
    if score >= 15:
        return "senior"
    return "mid"


def title_class(title: str) -> tuple[str, str]:
    """("clear" | "ambiguous" | "drop", reason)."""
    t = _words(title)
    if not t:
        return "drop", "no title"
    if _BUSINESS.search(t):
        return "drop", "business or sales role"
    if _QA.search(t):
        return "drop", "QA role"
    if _ROBOTICS.search(t):
        return "drop", "robotics role"
    is_eng = _ENG.search(t) or (_ENGINEERING.search(t) and _STRONG.search(t))
    if not is_eng:
        return "drop", "not an engineering title"
    if not _ROLE.search(t):
        return "drop", "not a software, ML or AI role"
    if _NOT_SOFTWARE.search(t) and not _STRONG.search(t):
        return "drop", "engineering outside software"
    level = seniority(t)
    if level == "intern":
        return "drop", "internship"
    if level == "senior":
        return "drop", "senior"
    return ("clear", "early-career title") if level == "entry" else ("ambiguous", "level not in title")


# ── Description pre-screen (free, before the model check) ────────────
# Drops only what the text states outright; everything else goes to the model.

_CLEARANCE = re.compile(
    r"(active|current|interim)\s+(dod\s+)?(secret|top secret|ts|ts/sci)\b|\bts/sci\b|top secret|security clearance|"
    r"clearance (is )?required|polygraph|(must|required to) (be|hold|have|possess|obtain|maintain)[^.]{0,60}clearance|"
    r"eligib\w+ (to obtain|for)[^.]{0,40}clearance|u\.?s\.? citizen(ship)? (is |status is )?(required|only)|"
    r"must be a u\.?s\.? citizen|requires? u\.?s\.? citizenship|\bitar\b|u\.?s\.? persons?\b",
    re.I,
)
_NO_CLEARANCE = re.compile(r"no (security )?clearance (is )?required|clearance (is )?not required", re.I)
_NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "ten": 10}
_YEARS = re.compile(
    r"(\d{1,2}|one|two|three|four|five|six|seven|eight|ten)\s*(\+|plus)?\s*(?:[-–—to]+\s*\d{1,2}\s*)?\+?\s*"
    r"(?:years?|yrs?)\b[^.\n]{0,60}?\b(experience|professional|industry|software|engineering|building|developing|working)",
    re.I,
)
_EARLY_WORDING = re.compile(
    r"new[\s-]*grad|recent(ly)? grad|graduating|class of 20(26|27)|entry[\s-]level|early[\s-]career|"
    r"0\s*[-–to]+\s*[12]\s*years|university grad|no (prior )?experience (is )?required|internship experience",
    re.I,
)


def min_years_required(description: str) -> int | None:
    """Smallest 'N years of experience' the text asks for, ignoring 'degree, or N years' alternatives."""
    found = []
    for m in _YEARS.finditer(description or ""):
        before = description[max(0, m.start() - 15):m.start()]
        if re.search(r"\bor\s*$", before, re.I):  # "…a CS degree, or 4+ years of experience"
            continue
        word = m.group(1).lower()
        years = int(word) if word.isdigit() else _NUMBER_WORDS[word]
        if years <= 15:
            found.append(years)
    return min(found) if found else None


def prescreen(description: str, title_cls: str) -> tuple[str, str]:
    """("drop" | "keep", reason) from the description text alone."""
    text = description or ""
    if _CLEARANCE.search(text) and not _NO_CLEARANCE.search(text):
        return "drop", "needs security clearance or US citizenship"
    if title_cls == "ambiguous" and not _EARLY_WORDING.search(text):
        years = min_years_required(text)
        if years is not None and years >= 3:
            return "drop", f"asks for {years}+ years of experience"
    return "keep", ""
