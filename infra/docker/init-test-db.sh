#!/bin/sh
set -eu
export MYSQL_PWD="$MYSQL_ROOT_PASSWORD"
mysql -uroot <<'SQL'
CREATE DATABASE IF NOT EXISTS vigilay_test CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
GRANT ALL PRIVILEGES ON vigilay_test.* TO 'vigilay'@'%';
SQL
