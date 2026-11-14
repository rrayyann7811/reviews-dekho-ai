-- Database schema as shipped in Phase 2 (commit d671346). Used to test upgrades.

CREATE TABLE products (
	id INTEGER NOT NULL, 
	name VARCHAR(200) NOT NULL, 
	brand VARCHAR(120), 
	category VARCHAR(120), 
	source VARCHAR(20) NOT NULL, 
	source_url VARCHAR(2000), 
	file_name VARCHAR(255), 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);

CREATE TABLE analysis_results (
	id INTEGER NOT NULL, 
	product_id INTEGER NOT NULL, 
	created_at DATETIME NOT NULL, 
	total_reviews INTEGER NOT NULL, 
	average_rating FLOAT, 
	positive_percent FLOAT NOT NULL, 
	negative_percent FLOAT NOT NULL, 
	stats JSON NOT NULL, 
	aspects JSON NOT NULL, 
	keywords JSON NOT NULL, 
	summary JSON NOT NULL, 
	ingestion JSON, 
	PRIMARY KEY (id), 
	FOREIGN KEY(product_id) REFERENCES products (id) ON DELETE CASCADE
);

CREATE INDEX ix_analysis_results_product_id ON analysis_results (product_id);

CREATE TABLE reviews (
	id INTEGER NOT NULL, 
	product_id INTEGER NOT NULL, 
	external_id VARCHAR(100) NOT NULL, 
	text TEXT NOT NULL, 
	rating INTEGER, 
	review_date DATE, 
	title VARCHAR(300), 
	reviewer VARCHAR(120), 
	sentiment VARCHAR(10), 
	score FLOAT, 
	mixed BOOLEAN NOT NULL, 
	aspects JSON NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_review_per_product UNIQUE (product_id, external_id), 
	FOREIGN KEY(product_id) REFERENCES products (id) ON DELETE CASCADE
);

CREATE INDEX ix_reviews_product_id ON reviews (product_id);
