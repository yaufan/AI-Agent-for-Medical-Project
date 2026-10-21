-- Synthetic ERP + QMS schema for "Company M", a vendor of lung-nodule CAD software
-- deployed on on-premise GPU inference appliances.
-- Portable SQL: runs unchanged on SQLite and PostgreSQL. Dates are ISO-8601 strings.

-- ===== ERP: customers, installed base, parts =====

CREATE TABLE sites (
    site_id        TEXT PRIMARY KEY,          -- e.g. H-A
    name           TEXT NOT NULL,             -- neutral names only: 醫院A, 醫院B, ...
    region         TEXT NOT NULL,             -- 北區 / 中區 / 南區 / 東區
    site_type      TEXT NOT NULL,             -- 醫學中心 / 區域醫院 / 地區醫院
    go_live_date   DATE NOT NULL
);

CREATE TABLE ct_scanners (
    scanner_id                TEXT PRIMARY KEY,
    site_id                   TEXT NOT NULL REFERENCES sites(site_id),
    vendor                    TEXT NOT NULL,  -- neutral: CT廠牌A / B / C
    model                     TEXT NOT NULL,
    default_slice_thickness_mm REAL NOT NULL, -- reconstruction the site sends to the CAD
    installed_at              DATE NOT NULL,
    retired_at                DATE
);

CREATE TABLE software_releases (
    version                   TEXT PRIMARY KEY,
    release_date              DATE NOT NULL,
    model_version             TEXT NOT NULL,
    max_slice_thickness_mm    REAL NOT NULL,  -- input spec checked by the service QC
    min_slices                INTEGER NOT NULL,
    regulatory_status         TEXT NOT NULL,  -- cleared / under_review / internal
    notes                     TEXT
);

CREATE TABLE suppliers (
    supplier_id    TEXT PRIMARY KEY,
    name           TEXT NOT NULL              -- neutral: 供應商甲 / 乙 / 丙
);

CREATE TABLE parts (
    part_no            TEXT PRIMARY KEY,
    category           TEXT NOT NULL,         -- GPU / SSD / CPU / RAM / PSU
    description        TEXT NOT NULL,
    supplier_id        TEXT NOT NULL REFERENCES suppliers(supplier_id),
    lifecycle_status   TEXT NOT NULL,         -- active / eol_announced
    eol_notice_date    DATE,
    last_time_buy_date DATE,
    datasheet_ref      TEXT                   -- key into the document corpus (filled in later)
);

CREATE TABLE appliance_skus (
    sku            TEXT PRIMARY KEY,
    description    TEXT NOT NULL
);

CREATE TABLE sku_bom (
    sku            TEXT NOT NULL REFERENCES appliance_skus(sku),
    part_no        TEXT NOT NULL REFERENCES parts(part_no),
    qty            INTEGER NOT NULL,
    PRIMARY KEY (sku, part_no)
);

CREATE TABLE part_lots (
    lot_no         TEXT PRIMARY KEY,
    part_no        TEXT NOT NULL REFERENCES parts(part_no),
    received_date  DATE NOT NULL,
    qty_received   INTEGER NOT NULL
);

CREATE TABLE appliances (
    serial_no      TEXT PRIMARY KEY,
    sku            TEXT NOT NULL REFERENCES appliance_skus(sku),
    site_id        TEXT NOT NULL REFERENCES sites(site_id),
    build_date     DATE NOT NULL,
    install_date   DATE NOT NULL,
    status         TEXT NOT NULL              -- in_service / replaced
);

-- Which physical lot went into which appliance (lot traceability).
CREATE TABLE appliance_parts (
    serial_no      TEXT NOT NULL REFERENCES appliances(serial_no),
    part_no        TEXT NOT NULL REFERENCES parts(part_no),
    lot_no         TEXT NOT NULL REFERENCES part_lots(lot_no),
    qty            INTEGER NOT NULL,
    PRIMARY KEY (serial_no, part_no)
);

CREATE TABLE licenses (
    license_id     TEXT PRIMARY KEY,
    site_id        TEXT NOT NULL REFERENCES sites(site_id),
    start_date     DATE NOT NULL,
    end_date       DATE NOT NULL,
    annual_fee_twd INTEGER NOT NULL
);

-- Software version history per appliance; the latest row is the current version.
CREATE TABLE deployments (
    deployment_id  TEXT PRIMARY KEY,
    serial_no      TEXT NOT NULL REFERENCES appliances(serial_no),
    version        TEXT NOT NULL REFERENCES software_releases(version),
    deployed_at    DATE NOT NULL
);

CREATE TABLE monthly_usage (
    site_id              TEXT NOT NULL REFERENCES sites(site_id),
    month                TEXT NOT NULL,       -- YYYY-MM
    studies_processed    INTEGER NOT NULL,
    qc_reject_rate       REAL NOT NULL,       -- share of studies rejected by input QC
    marks_per_study      REAL NOT NULL,       -- average CAD marks shown per accepted study
    mean_latency_s       REAL NOT NULL,
    PRIMARY KEY (site_id, month)
);

-- ===== QMS: complaints, CAPA, change control =====

CREATE TABLE capas (
    capa_id              TEXT PRIMARY KEY,
    title                TEXT NOT NULL,
    opened_at            DATE NOT NULL,
    due_date             DATE NOT NULL,
    closed_at            DATE,
    status               TEXT NOT NULL,       -- open / in_progress / closed
    root_cause_category  TEXT,                -- input_out_of_spec / supplier_component / software_defect / user_training / unknown
    owner_role           TEXT NOT NULL,       -- QA / RD / RA / Service
    description          TEXT NOT NULL
);

CREATE TABLE complaints (
    complaint_id     TEXT PRIMARY KEY,
    site_id          TEXT NOT NULL REFERENCES sites(site_id),
    received_at      DATE NOT NULL,
    category         TEXT NOT NULL,           -- false_positive_increase / missed_nodule / qc_reject / slow_inference / hardware_failure / ui_usability
    severity         TEXT NOT NULL,           -- low / medium / high
    scanner_id       TEXT REFERENCES ct_scanners(scanner_id),
    serial_no        TEXT REFERENCES appliances(serial_no),
    software_version TEXT REFERENCES software_releases(version),
    suspected_component TEXT,                 -- hardware complaints only: SSD / GPU / PSU / FAN
    description      TEXT NOT NULL,
    status           TEXT NOT NULL,           -- open / investigating / closed
    capa_id          TEXT REFERENCES capas(capa_id)
);

CREATE TABLE change_requests (
    ecr_id           TEXT PRIMARY KEY,
    change_type      TEXT NOT NULL,           -- component_change / model_update / sop_update
    title            TEXT NOT NULL,
    opened_at        DATE NOT NULL,
    status           TEXT NOT NULL,           -- draft / under_review / approved / rejected
    related_part_no  TEXT REFERENCES parts(part_no),
    related_version  TEXT REFERENCES software_releases(version),
    related_capa_id  TEXT REFERENCES capas(capa_id),
    description      TEXT NOT NULL
);
