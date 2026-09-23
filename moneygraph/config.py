"""Единственное место всех констант. Пороги подобраны по разведке данных (см. DESIGN.md §1.4)."""

ROLES = ["consolidator", "transit", "distributor", "terminal", "coordinator", "peripheral"]

LOUVAIN_SEED = 42
LOUVAIN_RESOLUTION = 1.0
MIN_COMPONENT_FOR_LOUVAIN = 5       # компоненты меньше — отдельный кластер целиком

# --- правила ролей ---
COORD_MIN_IN = 3
COORD_MIN_OUT = 3
COORD_BETWEENNESS_TOP_SHARE = 0.02  # топ-2 % по посредничеству
COORD_MIN_CLUSTERS = 2              # связан с >=2 кластерами

CONS_MIN_IN_DEG = 4
CONS_MAX_PASS = 0.30
CONS_SEED_MIN_SRC = 2               # альтернативный путь: >=2 seed платят напрямую
CONS_SEED_MAX_PASS = 0.50

DIST_MIN_OUT_DEG = 10
DIST_OUT_IN_RATIO = 3.0

TRANSIT_PASS_LO = 0.70
TRANSIT_PASS_HI = 1.30
TRANSIT_MIN_FAST_SHARE = 0.50       # доля исходящего, ушедшего <= FAST_DAYS после прихода
FAST_DAYS = 2

TERM_MIN_IN_KZT = 500_000
TERM_MIN_IN_DEG = 2

PERIPHERAL_SCORE = 0.20
EVIDENCE_MAX_LEN = 200

# --- приоритет ---
PRIORITY_WEIGHTS = {
    "in_kzt_rank": 0.30,
    "in_deg_rank": 0.20,
    "betweenness_rank": 0.15,
    "n_seed_src_norm": 0.15,
    "pagerank_rank": 0.10,
    "role_weight": 0.10,
}
ROLE_WEIGHT = {
    "coordinator": 1.0, "consolidator": 0.9, "distributor": 0.6,
    "transit": 0.5, "terminal": 0.4, "peripheral": 0.0,
}
TRUNCATED_PENALTY = 0.3
SEED_PENALTY = 0.5
TOP_N = 30

CYCLE_MAX_LEN = 5

# --- дробление (output/bursts.csv) ---
BURST_MIN_TX = 3                    # ≥3 перевода одной паре за один день: 93 пары-дня из 4 286
BURST_MIN_PAYERS = 4                # ≥4 разных плательщика одному получателю за день: 29 случаев

# --- устойчивость сети (output/resilience.csv) ---
RESILIENCE_STEPS = [0, 5, 10, 20, 30, 50]   # сколько узлов удаляем
RESILIENCE_RANDOM_RUNS = 20                 # случайная стратегия — среднее по прогонам
RESILIENCE_SEED = 42

# --- ассистент (LLM только формулирует ответ из готовых фактов, роли не присваивает) ---
ASSISTANT_MODEL = "gpt-5-mini"      # OpenAI; переопределяется переменной окружения OPENAI_MODEL
ASSISTANT_MAX_HOPS = 2              # глубина поиска общих получателей/плательщиков
ASSISTANT_TOP = 5                   # сколько кандидатов показывать
ASSISTANT_TIMEOUT_S = 60
