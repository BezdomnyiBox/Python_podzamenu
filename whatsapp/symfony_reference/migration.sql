-- Очередь исходящих WhatsApp-сообщений для офисного агента.
-- Скопируйте в Doctrine Migration или выполните вручную на БД CRM.

CREATE TABLE whatsapp_outbox (
    id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    agent_id        VARCHAR(64)  NOT NULL COMMENT 'ID офисного агента (CRM_AGENT_ID)',
    phone           VARCHAR(32)  NOT NULL,
    body            TEXT         NOT NULL,
    status          VARCHAR(20)  NOT NULL DEFAULT 'pending'
        COMMENT 'pending | processing | sent | failed',
    attempts        SMALLINT UNSIGNED NOT NULL DEFAULT 0,
    max_attempts    SMALLINT UNSIGNED NOT NULL DEFAULT 3,
    error_message   TEXT         NULL,
    external_message_id VARCHAR(128) NULL COMMENT 'ID от агента после отправки',
    order_id        BIGINT UNSIGNED NULL COMMENT 'Связь с заказом CRM (опционально)',
    scheduled_at    DATETIME     NULL COMMENT 'Не отдавать агенту раньше этого времени',
    locked_at       DATETIME     NULL,
    locked_by       VARCHAR(64)  NULL,
    sent_at         DATETIME     NULL,
    created_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    INDEX idx_outbox_fetch (agent_id, status, scheduled_at, created_at),
    INDEX idx_outbox_order (order_id),
    INDEX idx_outbox_locked (locked_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE whatsapp_agent_heartbeat (
    agent_id        VARCHAR(64)  NOT NULL PRIMARY KEY,
    logged_in       TINYINT(1)   NOT NULL DEFAULT 0,
    version         VARCHAR(32)  NULL,
    last_seen_at    DATETIME     NOT NULL,
    updated_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
