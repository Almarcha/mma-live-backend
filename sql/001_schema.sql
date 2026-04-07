-- ============================================================
--  MMA LIVE · Esquema completo de base de datos
--  Compatible con Supabase (PostgreSQL 15)
--  Ejecutar en: Supabase → SQL Editor → New Query
-- ============================================================

-- Habilitar extensiones necesarias
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";   -- búsqueda de texto difusa

-- ============================================================
-- 1. PAÍSES / NACIONALIDADES
-- ============================================================
CREATE TABLE IF NOT EXISTS countries (
    id          SERIAL PRIMARY KEY,
    code        CHAR(2)      NOT NULL UNIQUE,  -- 'US', 'ES', 'BR'...
    name        VARCHAR(100) NOT NULL,
    flag_emoji  VARCHAR(10),
    created_at  TIMESTAMPTZ  DEFAULT NOW()
);

-- ============================================================
-- 2. ORGANIZACIONES (UFC, Bellator, ONE, PFL...)
-- ============================================================
CREATE TABLE IF NOT EXISTS organizations (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(100) NOT NULL UNIQUE,  -- 'UFC', 'Bellator'
    short_name  VARCHAR(20),
    logo_url    TEXT,
    founded     DATE,
    created_at  TIMESTAMPTZ  DEFAULT NOW()
);

INSERT INTO organizations (name, short_name) VALUES
    ('Ultimate Fighting Championship', 'UFC'),
    ('Bellator MMA',                  'Bellator'),
    ('ONE Championship',              'ONE'),
    ('Professional Fighters League',  'PFL'),
    ('Rizin Fighting Federation',     'Rizin')
ON CONFLICT DO NOTHING;

-- ============================================================
-- 3. DIVISIONES DE PESO
-- ============================================================
CREATE TABLE IF NOT EXISTS weight_classes (
    id              SERIAL PRIMARY KEY,
    name            VARCHAR(50)  NOT NULL UNIQUE,  -- 'Heavyweight'
    name_es         VARCHAR(50),                   -- 'Peso pesado'
    weight_limit_lbs DECIMAL(5,1),
    weight_limit_kg  DECIMAL(5,1),
    gender          CHAR(1)      DEFAULT 'M',      -- 'M' / 'F'
    created_at      TIMESTAMPTZ  DEFAULT NOW()
);

INSERT INTO weight_classes (name, name_es, weight_limit_lbs, weight_limit_kg, gender) VALUES
    ('Strawweight',        'Peso paja',        115, 52.2, 'F'),
    ('Flyweight',          'Peso mosca',       125, 56.7, 'F'),
    ('Bantamweight',       'Peso gallo',       135, 61.2, 'F'),
    ('Featherweight',      'Peso pluma',       145, 65.8, 'F'),
    ('Strawweight Men',    'Peso paja masc.',  115, 52.2, 'M'),
    ('Flyweight Men',      'Peso mosca',       125, 56.7, 'M'),
    ('Bantamweight Men',   'Peso gallo',       135, 61.2, 'M'),
    ('Featherweight Men',  'Peso pluma',       145, 65.8, 'M'),
    ('Lightweight',        'Peso ligero',      155, 70.3, 'M'),
    ('Welterweight',       'Peso wélter',      170, 77.1, 'M'),
    ('Middleweight',       'Peso medio',       185, 83.9, 'M'),
    ('Light Heavyweight',  'Semipesado',       205, 93.0, 'M'),
    ('Heavyweight',        'Peso pesado',      265,120.2, 'M'),
    ('Super Heavyweight',  'Superpesado',      NULL, NULL,'M'),
    ('Open Weight',        'Peso abierto',     NULL, NULL,'M')
ON CONFLICT DO NOTHING;

-- ============================================================
-- 4. GIMNASIOS / EQUIPOS
-- ============================================================
CREATE TABLE IF NOT EXISTS gyms (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(150) NOT NULL,
    city        VARCHAR(100),
    country_id  INT REFERENCES countries(id),
    created_at  TIMESTAMPTZ  DEFAULT NOW()
);

-- ============================================================
-- 5. PELEADORES (tabla principal)
-- ============================================================
CREATE TABLE IF NOT EXISTS fighters (
    id                  UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    -- Identificadores externos
    ufc_id              VARCHAR(50) UNIQUE,        -- ID en ufc.com
    ufc_slug            VARCHAR(100) UNIQUE,       -- 'israel-adesanya'
    tapology_id         VARCHAR(50),
    sherdog_id          VARCHAR(50),

    -- Datos personales
    first_name          VARCHAR(100) NOT NULL,
    last_name           VARCHAR(100) NOT NULL,
    nickname            VARCHAR(100),
    full_name           VARCHAR(200) GENERATED ALWAYS AS (first_name || ' ' || last_name) STORED,

    -- Origen
    nationality_id      INT REFERENCES countries(id),
    birth_city          VARCHAR(100),
    birth_country_id    INT REFERENCES countries(id),
    date_of_birth       DATE,

    -- Físico
    height_cm           DECIMAL(5,1),
    reach_cm            DECIMAL(5,1),
    leg_reach_cm        DECIMAL(5,1),
    stance              VARCHAR(20),   -- 'Orthodox', 'Southpaw', 'Switch'

    -- Categoría principal
    primary_weight_class_id INT REFERENCES weight_classes(id),
    gender              CHAR(1) DEFAULT 'M',

    -- Estado
    status              VARCHAR(20) DEFAULT 'Active',
    -- 'Active', 'Retired', 'Inactive', 'Suspended', 'Deceased'
    retired_date        DATE,
    retirement_reason   TEXT,

    -- Organización actual
    org_id              INT REFERENCES organizations(id),
    gym_id              INT REFERENCES gyms(id),
    team_name           VARCHAR(150),

    -- Récord profesional (calculado y cacheado)
    wins                INT DEFAULT 0,
    losses              INT DEFAULT 0,
    draws               INT DEFAULT 0,
    no_contests         INT DEFAULT 0,
    -- Desglose de victorias
    wins_ko             INT DEFAULT 0,
    wins_sub            INT DEFAULT 0,
    wins_dec            INT DEFAULT 0,
    -- Desglose de derrotas
    losses_ko           INT DEFAULT 0,
    losses_sub          INT DEFAULT 0,
    losses_dec          INT DEFAULT 0,

    -- Rankings / Títulos
    ufc_ranking         INT,
    is_champion         BOOLEAN DEFAULT FALSE,
    is_interim_champion BOOLEAN DEFAULT FALSE,
    title_weight_class_id INT REFERENCES weight_classes(id),

    -- Estadísticas avanzadas UFC
    sig_str_landed_pm   DECIMAL(5,2),  -- strikes significativos por minuto
    sig_str_accuracy    DECIMAL(5,2),  -- % precisión
    sig_str_absorbed_pm DECIMAL(5,2),
    sig_str_defense     DECIMAL(5,2),
    td_avg              DECIMAL(5,2),  -- takedowns por 15 min
    td_accuracy         DECIMAL(5,2),
    td_defense          DECIMAL(5,2),
    sub_avg             DECIMAL(5,2),  -- intentos de sumisión por 15 min

    -- Media
    profile_image_url   TEXT,
    ufc_profile_url     TEXT,

    -- Meta
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW(),
    last_scraped_at     TIMESTAMPTZ
);

-- Índices para búsquedas frecuentes
CREATE INDEX IF NOT EXISTS idx_fighters_last_name    ON fighters(last_name);
CREATE INDEX IF NOT EXISTS idx_fighters_status       ON fighters(status);
CREATE INDEX IF NOT EXISTS idx_fighters_weight_class ON fighters(primary_weight_class_id);
CREATE INDEX IF NOT EXISTS idx_fighters_ufc_slug     ON fighters(ufc_slug);
CREATE INDEX IF NOT EXISTS idx_fighters_fulltext     ON fighters USING gin(full_name gin_trgm_ops);

-- ============================================================
-- 6. EVENTOS
-- ============================================================
CREATE TABLE IF NOT EXISTS events (
    id              UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    -- Identificadores externos
    ufc_event_id    VARCHAR(50) UNIQUE,
    ufc_slug        VARCHAR(150) UNIQUE,

    -- Datos del evento
    name            VARCHAR(200) NOT NULL,
    short_name      VARCHAR(100),           -- 'UFC 300', 'FN 271'
    org_id          INT REFERENCES organizations(id),
    event_type      VARCHAR(30),            -- 'Numbered', 'Fight Night', 'Special'
    event_number    INT,                    -- 300 para UFC 300

    -- Fecha y lugar
    event_date      DATE        NOT NULL,
    event_time_utc  TIMESTAMPTZ,
    venue           VARCHAR(200),
    city            VARCHAR(100),
    country_id      INT REFERENCES countries(id),
    state_region    VARCHAR(100),

    -- Estado
    status          VARCHAR(20) DEFAULT 'Upcoming',
    -- 'Upcoming', 'Live', 'Completed', 'Cancelled'

    -- Difusión
    broadcast       VARCHAR(100),           -- 'ESPN+ PPV', 'Paramount+'
    ppv             BOOLEAN DEFAULT FALSE,
    ppv_price_usd   DECIMAL(5,2),

    -- Meta
    ufc_url         TEXT,
    thumbnail_url   TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    last_scraped_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_events_date   ON events(event_date DESC);
CREATE INDEX IF NOT EXISTS idx_events_status ON events(status);

-- ============================================================
-- 7. COMBATES
-- ============================================================
CREATE TABLE IF NOT EXISTS fights (
    id                  UUID    PRIMARY KEY DEFAULT uuid_generate_v4(),
    ufc_fight_id        VARCHAR(50) UNIQUE,

    -- Relaciones
    event_id            UUID    NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    fighter_a_id        UUID    NOT NULL REFERENCES fighters(id),
    fighter_b_id        UUID    NOT NULL REFERENCES fighters(id),
    weight_class_id     INT     REFERENCES weight_classes(id),

    -- Posición en la cartelera
    card_position       INT,               -- 1 = main event
    card_segment        VARCHAR(20),       -- 'Main Card', 'Prelims', 'Early Prelims'
    is_main_event       BOOLEAN DEFAULT FALSE,
    is_co_main          BOOLEAN DEFAULT FALSE,
    is_title_fight      BOOLEAN DEFAULT FALSE,
    is_interim_title    BOOLEAN DEFAULT FALSE,
    is_catch_weight     BOOLEAN DEFAULT FALSE,

    -- Programación
    scheduled_rounds    INT DEFAULT 3,
    weight_agreed_lbs   DECIMAL(5,1),

    -- Resultado
    status              VARCHAR(20) DEFAULT 'Scheduled',
    -- 'Scheduled', 'Completed', 'Cancelled', 'No Contest'
    winner_id           UUID    REFERENCES fighters(id),
    result              VARCHAR(20),
    -- 'KO/TKO', 'Submission', 'Decision - Unanimous',
    -- 'Decision - Split', 'Decision - Majority', 'No Contest', 'Draw'
    result_round        INT,
    result_time         VARCHAR(10),       -- '4:32'
    result_details      TEXT,              -- 'Rear Naked Choke', 'Head Kick'

    -- Odds (cuotas moneyline al momento del combate)
    odds_fighter_a      DECIMAL(7,2),
    odds_fighter_b      DECIMAL(7,2),

    -- Estadísticas del combate (Fighter A)
    a_sig_str_landed    INT,
    a_sig_str_attempted INT,
    a_total_str_landed  INT,
    a_total_str_att     INT,
    a_td_landed         INT,
    a_td_attempted      INT,
    a_sub_attempts      INT,
    a_reversals         INT,
    a_ctrl_time_secs    INT,               -- segundos de control

    -- Estadísticas del combate (Fighter B)
    b_sig_str_landed    INT,
    b_sig_str_attempted INT,
    b_total_str_landed  INT,
    b_total_str_att     INT,
    b_td_landed         INT,
    b_td_attempted      INT,
    b_sub_attempts      INT,
    b_reversals         INT,
    b_ctrl_time_secs    INT,

    -- Meta
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_fights_event    ON fights(event_id);
CREATE INDEX IF NOT EXISTS idx_fights_fighter_a ON fights(fighter_a_id);
CREATE INDEX IF NOT EXISTS idx_fights_fighter_b ON fights(fighter_b_id);
CREATE INDEX IF NOT EXISTS idx_fights_status   ON fights(status);

-- ============================================================
-- 8. TÍTULOS / HISTORIAL DE CAMPEONES
-- ============================================================
CREATE TABLE IF NOT EXISTS title_history (
    id              SERIAL      PRIMARY KEY,
    fighter_id      UUID        NOT NULL REFERENCES fighters(id),
    weight_class_id INT         NOT NULL REFERENCES weight_classes(id),
    org_id          INT         REFERENCES organizations(id),
    is_interim      BOOLEAN     DEFAULT FALSE,
    won_date        DATE,
    won_fight_id    UUID        REFERENCES fights(id),
    lost_date       DATE,
    lost_fight_id   UUID        REFERENCES fights(id),
    vacated_date    DATE,
    defenses        INT         DEFAULT 0,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- 9. RANKINGS HISTÓRICOS
-- ============================================================
CREATE TABLE IF NOT EXISTS rankings (
    id              SERIAL      PRIMARY KEY,
    fighter_id      UUID        NOT NULL REFERENCES fighters(id),
    weight_class_id INT         NOT NULL REFERENCES weight_classes(id),
    org_id          INT         REFERENCES organizations(id),
    rank_position   INT         NOT NULL,   -- 0 = campeón, 1-15 = ranking
    is_pound_for_pound BOOLEAN  DEFAULT FALSE,
    rank_date       DATE        NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_rankings_fighter  ON rankings(fighter_id);
CREATE INDEX IF NOT EXISTS idx_rankings_date     ON rankings(rank_date DESC);

-- ============================================================
-- 10. USUARIOS (complementa Supabase Auth)
-- ============================================================
-- NOTA: Supabase Auth crea automáticamente auth.users
-- Esta tabla extiende el perfil público de cada usuario
CREATE TABLE IF NOT EXISTS user_profiles (
    id              UUID        PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    username        VARCHAR(50) UNIQUE,
    display_name    VARCHAR(100),
    avatar_url      TEXT,
    bio             TEXT,
    country_id      INT         REFERENCES countries(id),
    is_premium      BOOLEAN     DEFAULT FALSE,
    premium_until   TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- 11. PELEADORES FAVORITOS DE USUARIOS
-- ============================================================
CREATE TABLE IF NOT EXISTS user_favorite_fighters (
    user_id     UUID REFERENCES user_profiles(id) ON DELETE CASCADE,
    fighter_id  UUID REFERENCES fighters(id)      ON DELETE CASCADE,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (user_id, fighter_id)
);

-- ============================================================
-- 12. PREDICCIONES DE USUARIOS
-- ============================================================
CREATE TABLE IF NOT EXISTS user_predictions (
    id                  SERIAL      PRIMARY KEY,
    user_id             UUID        NOT NULL REFERENCES user_profiles(id) ON DELETE CASCADE,
    fight_id            UUID        NOT NULL REFERENCES fights(id)        ON DELETE CASCADE,
    predicted_winner_id UUID        NOT NULL REFERENCES fighters(id),
    predicted_method    VARCHAR(30),
    predicted_round     INT,
    confidence          INT         CHECK (confidence BETWEEN 1 AND 10),
    was_correct         BOOLEAN,    -- NULL hasta que el combate termine
    points_earned       INT         DEFAULT 0,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (user_id, fight_id)
);

CREATE INDEX IF NOT EXISTS idx_predictions_user  ON user_predictions(user_id);
CREATE INDEX IF NOT EXISTS idx_predictions_fight ON user_predictions(fight_id);

-- ============================================================
-- 13. NOTIFICACIONES / ALERTAS
-- ============================================================
CREATE TABLE IF NOT EXISTS user_notifications (
    id          SERIAL      PRIMARY KEY,
    user_id     UUID        NOT NULL REFERENCES user_profiles(id) ON DELETE CASCADE,
    type        VARCHAR(30) NOT NULL,
    -- 'event_reminder', 'fight_result', 'fighter_news', 'prediction_result'
    title       VARCHAR(200),
    body        TEXT,
    data        JSONB,              -- payload extra (fight_id, fighter_id...)
    read        BOOLEAN     DEFAULT FALSE,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- 14. CONTROL DEL SCRAPER
-- ============================================================
CREATE TABLE IF NOT EXISTS scraper_log (
    id          SERIAL      PRIMARY KEY,
    scraper     VARCHAR(50) NOT NULL,  -- 'ufc_fighters', 'ufc_events'...
    status      VARCHAR(20) NOT NULL,  -- 'success', 'error', 'partial'
    records_new INT         DEFAULT 0,
    records_upd INT         DEFAULT 0,
    records_err INT         DEFAULT 0,
    message     TEXT,
    started_at  TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- 15. TRIGGERS: actualizar updated_at automáticamente
-- ============================================================
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_fighters_updated_at
    BEFORE UPDATE ON fighters
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER trg_events_updated_at
    BEFORE UPDATE ON events
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER trg_fights_updated_at
    BEFORE UPDATE ON fights
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- ============================================================
-- 16. TRIGGER: crear perfil automáticamente al registrarse
-- ============================================================
CREATE OR REPLACE FUNCTION handle_new_user()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO public.user_profiles (id, display_name, avatar_url)
    VALUES (
        NEW.id,
        COALESCE(NEW.raw_user_meta_data->>'full_name', split_part(NEW.email, '@', 1)),
        NEW.raw_user_meta_data->>'avatar_url'
    );
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

CREATE TRIGGER trg_on_auth_user_created
    AFTER INSERT ON auth.users
    FOR EACH ROW EXECUTE FUNCTION handle_new_user();

-- ============================================================
-- 17. ROW LEVEL SECURITY (RLS) — Seguridad por filas
-- ============================================================

-- Habilitar RLS en tablas sensibles
ALTER TABLE user_profiles         ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_favorite_fighters ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_predictions      ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_notifications    ENABLE ROW LEVEL SECURITY;

-- user_profiles: cada usuario solo ve/edita su propio perfil
CREATE POLICY "users_own_profile_select" ON user_profiles
    FOR SELECT USING (auth.uid() = id);

CREATE POLICY "users_own_profile_update" ON user_profiles
    FOR UPDATE USING (auth.uid() = id);

-- Favoritos: solo el dueño
CREATE POLICY "users_own_favorites" ON user_favorite_fighters
    FOR ALL USING (auth.uid() = user_id);

-- Predicciones: el dueño gestiona las suyas, todos pueden ver resultados
CREATE POLICY "users_own_predictions_write" ON user_predictions
    FOR INSERT WITH CHECK (auth.uid() = user_id);

CREATE POLICY "users_own_predictions_read" ON user_predictions
    FOR SELECT USING (auth.uid() = user_id);

-- Notificaciones: solo el dueño
CREATE POLICY "users_own_notifications" ON user_notifications
    FOR ALL USING (auth.uid() = user_id);

-- Tablas públicas (lectura libre, escritura solo desde service role)
ALTER TABLE fighters        ENABLE ROW LEVEL SECURITY;
ALTER TABLE events          ENABLE ROW LEVEL SECURITY;
ALTER TABLE fights          ENABLE ROW LEVEL SECURITY;
ALTER TABLE weight_classes  ENABLE ROW LEVEL SECURITY;
ALTER TABLE countries       ENABLE ROW LEVEL SECURITY;

CREATE POLICY "public_read_fighters"       ON fighters       FOR SELECT USING (true);
CREATE POLICY "public_read_events"         ON events         FOR SELECT USING (true);
CREATE POLICY "public_read_fights"         ON fights         FOR SELECT USING (true);
CREATE POLICY "public_read_weight_classes" ON weight_classes FOR SELECT USING (true);
CREATE POLICY "public_read_countries"      ON countries      FOR SELECT USING (true);

-- ============================================================
-- 18. VISTAS ÚTILES
-- ============================================================

-- Vista: ranking actual por división
CREATE OR REPLACE VIEW current_rankings AS
SELECT DISTINCT ON (r.weight_class_id, r.rank_position)
    f.full_name,
    f.ufc_slug,
    f.wins, f.losses, f.draws,
    f.status AS fighter_status,
    f.profile_image_url,
    wc.name_es AS weight_class,
    r.rank_position,
    r.rank_date
FROM rankings r
JOIN fighters f      ON f.id = r.fighter_id
JOIN weight_classes wc ON wc.id = r.weight_class_id
ORDER BY r.weight_class_id, r.rank_position, r.rank_date DESC;

-- Vista: próximos eventos con cartelera
CREATE OR REPLACE VIEW upcoming_events_with_fights AS
SELECT
    e.id AS event_id,
    e.name AS event_name,
    e.event_date,
    e.venue,
    e.city,
    e.status,
    e.event_type,
    count(fi.id) AS total_fights,
    sum(CASE WHEN fi.is_title_fight THEN 1 ELSE 0 END) AS title_fights
FROM events e
LEFT JOIN fights fi ON fi.event_id = e.id
WHERE e.event_date >= CURRENT_DATE
GROUP BY e.id
ORDER BY e.event_date ASC;

-- Vista: historial completo de un peleador (para perfil)
CREATE OR REPLACE VIEW fighter_fight_history AS
SELECT
    f.id AS fight_id,
    e.name AS event_name,
    e.event_date,
    fa.full_name AS fighter_a,
    fa.id        AS fighter_a_id,
    fb.full_name AS fighter_b,
    fb.id        AS fighter_b_id,
    fw.full_name AS winner,
    f.result,
    f.result_round,
    f.result_time,
    f.result_details,
    f.is_title_fight,
    wc.name_es   AS weight_class
FROM fights f
JOIN events      e  ON e.id  = f.event_id
JOIN fighters    fa ON fa.id = f.fighter_a_id
JOIN fighters    fb ON fb.id = f.fighter_b_id
LEFT JOIN fighters fw ON fw.id = f.winner_id
LEFT JOIN weight_classes wc ON wc.id = f.weight_class_id
ORDER BY e.event_date DESC;
