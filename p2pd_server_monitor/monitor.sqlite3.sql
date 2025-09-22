BEGIN TRANSACTION;
CREATE TABLE IF NOT EXISTS "aliases" (
	"id"	INTEGER,
	"fqn"	TEXT NOT NULL,
	"af"	INTEGER NOT NULL CHECK("af" IN (2, 10)),
	"ip"	TEXT DEFAULT NULL,
	UNIQUE("fqn","af"),
	PRIMARY KEY("id" AUTOINCREMENT)
);
CREATE TABLE IF NOT EXISTS "groups" (
	"id"	INTEGER,
	PRIMARY KEY("id" AUTOINCREMENT)
);
CREATE TABLE IF NOT EXISTS "imports" (
	"id"	INTEGER,
	"type"	INTEGER NOT NULL CHECK("type" BETWEEN 1 AND 5),
	"af"	INTEGER NOT NULL CHECK("af" IN (2, 10)),
	"ip"	TEXT NOT NULL,
	"port"	INTEGER NOT NULL CHECK("port" BETWEEN 1 AND 65535),
	"user"	TEXT DEFAULT NULL,
	"pass"	TEXT DEFAULT NULL,
	"alias_id"	INTEGER DEFAULT NULL,
	PRIMARY KEY("id" AUTOINCREMENT),
	UNIQUE("type","af","ip","port"),
	FOREIGN KEY("alias_id") REFERENCES "aliases"("id")
);
CREATE TABLE IF NOT EXISTS "services" (
	"id"	INTEGER,
	"type"	INTEGER NOT NULL CHECK("type" BETWEEN 1 AND 5),
	"af"	INTEGER NOT NULL CHECK("af" IN (2, 10)),
	"proto"	INTEGER NOT NULL CHECK("proto" IN (1, 2)),
	"ip"	TEXT NOT NULL,
	"port"	INTEGER NOT NULL CHECK("port" BETWEEN 1 AND 65535),
	"group_id"	INTEGER NOT NULL,
	"user"	TEXT DEFAULT NULL,
	"pass"	TEXT DEFAULT NULL,
	"alias_id"	INTEGER DEFAULT NULL,
	PRIMARY KEY("id" AUTOINCREMENT),
	UNIQUE("type","af","proto","ip","port"),
	FOREIGN KEY("alias_id") REFERENCES "aliases"("id")
);
CREATE TABLE IF NOT EXISTS "settings" (
	"key"	TEXT,
	"value"	INTEGER,
	PRIMARY KEY("key")
);
CREATE TABLE IF NOT EXISTS "status" (
	"id"	INTEGER,
	"table_type"	INTEGER CHECK("table_type" BETWEEN 1 AND 3),
	"row_id"	INTEGER,
	"status"	INTEGER NOT NULL DEFAULT 0 CHECK("status" IN (0, 1, 2)),
	"last_status"	INTEGER NOT NULL CHECK("last_status" >= 1735689600 AND "last_status" <= 32503680000),
	"test_no"	INTEGER NOT NULL DEFAULT 0,
	"failed_tests"	INTEGER NOT NULL DEFAULT 0 CHECK("failed_tests" <= "test_no"),
	"last_success"	INTEGER NOT NULL DEFAULT 0 CHECK("last_success" = 0 OR ("last_success" >= 1735689600 AND "last_success" <= 32503680000)),
	"uptime"	INTEGER NOT NULL DEFAULT 0,
	"max_uptime"	INTEGER NOT NULL DEFAULT 0,
	"last_uptime"	INTEGER NOT NULL DEFAULT 0 CHECK("last_uptime" = 0 OR ("last_uptime" >= 1735689600 AND "last_uptime" <= 32503680000)),
	PRIMARY KEY("id" AUTOINCREMENT)
);
CREATE VIEW service_quality AS
WITH server_scores AS (
    SELECT
        services.group_id,
        services.id AS service_id,
        services.ip,
        services.af,
        services.proto,
        services.type,
        status.id AS status_id,
        status.failed_tests,
        status.test_no,
        status.uptime,
        status.max_uptime,
        status.last_status AS last_success,
        (
            (1.0 - CAST(status.failed_tests AS REAL) / (status.test_no + 1e-9))
            *
            (0.5 * CASE WHEN status.max_uptime > 0 
                        THEN status.uptime / status.max_uptime 
                        ELSE 1.0 END + 0.5)
            *
            (1.0 - EXP(-CAST(status.test_no AS REAL) / 50.0))
        ) AS quality_score,
        (
            SELECT GROUP_CONCAT(fqn)
            FROM aliases
            WHERE aliases.ip = services.ip 
              AND aliases.af = services.af
        ) AS aliases
    FROM services
    JOIN status 
      ON status.row_id = services.id
     AND status.table_type = 1 -- hard-coded; replace with actual table_type if fixed
),
group_scores AS (
    SELECT
        group_id,
        AVG(quality_score) AS group_score
    FROM server_scores
    GROUP BY group_id
)
SELECT
    s.group_id,
    g.group_score,
    s.service_id,
    s.status_id,
    s.ip,
    s.af,
    s.proto,
    s.type,
    s.quality_score,
    s.uptime,
    s.max_uptime,
    s.last_success,
    s.aliases
FROM server_scores s
JOIN group_scores g 
  ON g.group_id = s.group_id;
CREATE TRIGGER delete_status_on_aliases
AFTER DELETE ON aliases
FOR EACH ROW
BEGIN
    DELETE FROM status WHERE table_type = 2 AND row_id = OLD.id;
END;
CREATE TRIGGER delete_status_on_imports
AFTER DELETE ON imports
FOR EACH ROW
BEGIN
    DELETE FROM status WHERE table_type = 3 AND row_id = OLD.id;
END;
CREATE TRIGGER delete_status_on_services
AFTER DELETE ON services
FOR EACH ROW
BEGIN
    DELETE FROM status WHERE table_type = 1 AND row_id = OLD.id;
END;
CREATE TRIGGER filter_secondary_stun_ips
BEFORE INSERT ON services
FOR EACH ROW
WHEN NEW.type = 1 AND NEW.proto = 2
BEGIN
    -- Count existing type=2, proto=2 rows in this group
    SELECT
    CASE
        WHEN (
            SELECT COUNT(*) 
            FROM services
            WHERE group_id = NEW.group_id
              AND type = 2
              AND proto = 2
        ) >= 2
        AND EXISTS (
            SELECT 1 FROM services
            WHERE type = 2
              AND ip = NEW.ip
              AND af = NEW.af
        )
        THEN RAISE(ABORT, 'Conflict: type 1 with same ip and af exists')
    END;
END;
CREATE TRIGGER reset_uptime_on_failure
AFTER UPDATE OF failed_tests ON status
FOR EACH ROW
WHEN NEW.failed_tests > OLD.failed_tests
BEGIN
    UPDATE status
    SET uptime = 0,
        last_uptime = 0
    WHERE id = NEW.id;
END;
CREATE TRIGGER update_max_uptime
AFTER UPDATE OF uptime ON status
FOR EACH ROW
WHEN NEW.uptime > OLD.max_uptime
BEGIN
    UPDATE status
    SET max_uptime = NEW.uptime
    WHERE id = NEW.id;
END;
COMMIT;
