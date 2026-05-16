DROP TABLE IF EXISTS orders;
DROP TABLE IF EXISTS accounts;

CREATE TABLE accounts (
    id INT PRIMARY KEY,
    owner_name VARCHAR(50) NOT NULL,
    balance INT NOT NULL
) ENGINE=InnoDB;

CREATE TABLE orders (
    id INT PRIMARY KEY AUTO_INCREMENT,
    account_id INT NOT NULL,
    amount INT NOT NULL,
    status VARCHAR(20) NOT NULL,
    FOREIGN KEY (account_id) REFERENCES accounts(id)
) ENGINE=InnoDB;

INSERT INTO accounts (id, owner_name, balance) VALUES
    (1, 'Ivan', 500),
    (2, 'Maria', 900);

INSERT INTO orders (account_id, amount, status) VALUES
    (1, 100, 'new'),
    (1, 250, 'new'),
    (2, 400, 'paid');
