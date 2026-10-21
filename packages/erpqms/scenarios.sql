-- Reference queries for the planted storylines. They double as SQL practice and as
-- ground truth for agent evaluation: an agent answering the same question in natural
-- language should reach the same rows. Reference date: 2026-09-30.

-- name: s1_new_ct_complaints
-- Which sites run the new C-320 scanner, how many complaints came from it, and how many are linked to a CAPA?
SELECT s.site_id, s.name, ct.scanner_id, ct.installed_at, ct.default_slice_thickness_mm,
       COUNT(c.complaint_id)  AS complaints,
       COUNT(c.capa_id)       AS linked_to_capa
FROM ct_scanners ct
JOIN sites s       ON s.site_id = ct.site_id
LEFT JOIN complaints c ON c.scanner_id = ct.scanner_id
WHERE ct.model = 'C-320'
GROUP BY s.site_id, s.name, ct.scanner_id, ct.installed_at, ct.default_slice_thickness_mm
ORDER BY ct.installed_at;

-- name: s1_out_of_spec_scanners
-- Scanners whose default reconstruction exceeds the input spec of the version deployed at the same site.
SELECT DISTINCT ct.site_id, ct.scanner_id, ct.model, ct.default_slice_thickness_mm, r.max_slice_thickness_mm
FROM ct_scanners ct
JOIN appliances a        ON a.site_id = ct.site_id
JOIN deployments dep     ON dep.serial_no = a.serial_no
JOIN software_releases r ON r.version = dep.version
WHERE ct.default_slice_thickness_mm > r.max_slice_thickness_mm
ORDER BY ct.site_id;

-- name: s1_usage_before_after
-- Monthly QC reject rate and CAD marks per study at 醫院B around the new scanner.
SELECT month, studies_processed, qc_reject_rate, marks_per_study
FROM monthly_usage
WHERE site_id = 'H-B' AND month BETWEEN '2026-03' AND '2026-09'
ORDER BY month;

-- name: s2_bad_lot_trace
-- Every appliance built with SSD lot SSD-S1-L2508, and whether it has already failed.
SELECT a.serial_no, a.site_id, s.name, a.build_date,
       COUNT(c.complaint_id) AS ssd_failures
FROM appliance_parts ap
JOIN appliances a ON a.serial_no = ap.serial_no
JOIN sites s      ON s.site_id = a.site_id
LEFT JOIN complaints c ON c.serial_no = a.serial_no AND c.suspected_component = 'SSD'
WHERE ap.lot_no = 'SSD-S1-L2508'
GROUP BY a.serial_no, a.site_id, s.name, a.build_date
ORDER BY ssd_failures DESC, a.serial_no;

-- name: s2_failure_rate_by_lot
-- SSD failures per SSD lot, normalised by the number of appliances carrying it.
-- Filtering on suspected_component matters: grouping every hardware_failure (fans, power
-- supplies) by SSD lot makes a one-appliance lot look like the worst one.
SELECT ap.lot_no,
       COUNT(DISTINCT ap.serial_no)                              AS appliances,
       COUNT(DISTINCT c.serial_no)                               AS appliances_failed,
       ROUND(1.0 * COUNT(DISTINCT c.serial_no) / COUNT(DISTINCT ap.serial_no), 2) AS failure_share
FROM appliance_parts ap
LEFT JOIN complaints c ON c.serial_no = ap.serial_no AND c.suspected_component = 'SSD'
WHERE ap.part_no LIKE 'SSD-%'
GROUP BY ap.lot_no
ORDER BY failure_share DESC, ap.lot_no;

-- name: s3_eol_gpu_exposure
-- Installed appliances that carry an end-of-life part, per site.
SELECT p.part_no, p.last_time_buy_date, a.site_id, COUNT(*) AS appliances
FROM parts p
JOIN appliance_parts ap ON ap.part_no = p.part_no
JOIN appliances a       ON a.serial_no = ap.serial_no
WHERE p.lifecycle_status = 'eol_announced' AND a.status = 'in_service'
GROUP BY p.part_no, p.last_time_buy_date, a.site_id
ORDER BY a.site_id;

-- name: s4_current_versions
-- Current software version per appliance (latest deployment row).
SELECT a.site_id, a.serial_no, dep.version, dep.deployed_at
FROM appliances a
JOIN deployments dep ON dep.serial_no = a.serial_no
WHERE dep.deployed_at = (SELECT MAX(d2.deployed_at) FROM deployments d2 WHERE d2.serial_no = a.serial_no)
ORDER BY a.site_id, a.serial_no;

-- name: s4_overdue_capas
-- CAPAs past their due date and not closed.
SELECT capa_id, title, due_date, status, owner_role
FROM capas
WHERE status <> 'closed' AND due_date < '2026-09-30'
ORDER BY due_date;
