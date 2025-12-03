/**
 * MongoDB Setup Script for Innovate UK Scraper
 *
 * Run with: mongosh < mongo_setup.js
 * Or: mongosh "mongodb://localhost:27017" < mongo_setup.js
 *
 * This script creates:
 * - Database: ailsa_grants
 * - Collection: grants
 * - Indexes for efficient querying
 */

// Switch to the database (creates if doesn't exist)
use("ailsa_grants");

// Create the grants collection with schema validation
db.createCollection("grants", {
  validator: {
    $jsonSchema: {
      bsonType: "object",
      required: ["grant_id", "source", "title", "url"],
      properties: {
        grant_id: {
          bsonType: "string",
          description: "Unique identifier for the grant"
        },
        source: {
          bsonType: "string",
          description: "Source of the grant (e.g., innovate_uk)"
        },
        title: {
          bsonType: "string",
          description: "Grant title"
        },
        url: {
          bsonType: "string",
          description: "URL to the grant page"
        },
        external_id: {
          bsonType: ["string", "null"],
          description: "External ID from the source"
        },
        status: {
          enum: ["active", "closed", null],
          description: "Grant status"
        },
        is_active: {
          bsonType: "bool",
          description: "Whether the grant is currently active"
        },
        competition_type: {
          enum: ["grant", "loan", "prize", null],
          description: "Type of competition"
        },
        total_fund_gbp: {
          bsonType: ["int", "long", "null"],
          description: "Total funding in GBP"
        },
        project_funding_min: {
          bsonType: ["int", "long", "null"],
          description: "Minimum per-project funding in GBP"
        },
        project_funding_max: {
          bsonType: ["int", "long", "null"],
          description: "Maximum per-project funding in GBP"
        },
        expected_winners: {
          bsonType: ["int", "null"],
          description: "Expected number of winners"
        }
      }
    }
  },
  validationLevel: "moderate",
  validationAction: "warn"
});

print("Created grants collection with schema validation");

// Create indexes
// Primary unique index on grant_id
db.grants.createIndex(
  { grant_id: 1 },
  { unique: true, name: "idx_grant_id" }
);
print("Created unique index on grant_id");

// Index for querying by source
db.grants.createIndex(
  { source: 1 },
  { name: "idx_source" }
);
print("Created index on source");

// Index for querying active grants
db.grants.createIndex(
  { is_active: 1 },
  { name: "idx_is_active" }
);
print("Created index on is_active");

// Index for querying by status
db.grants.createIndex(
  { status: 1 },
  { name: "idx_status" }
);
print("Created index on status");

// Index for querying by competition type
db.grants.createIndex(
  { competition_type: 1 },
  { name: "idx_competition_type" }
);
print("Created index on competition_type");

// Index for querying by close date (for deadline-based queries)
db.grants.createIndex(
  { closes_at: 1 },
  { name: "idx_closes_at" }
);
print("Created index on closes_at");

// Compound index for common query pattern: source + status
db.grants.createIndex(
  { source: 1, status: 1 },
  { name: "idx_source_status" }
);
print("Created compound index on source + status");

// Compound index for active grants by source
db.grants.createIndex(
  { source: 1, is_active: 1 },
  { name: "idx_source_active" }
);
print("Created compound index on source + is_active");

// Text index for full-text search on title and description
db.grants.createIndex(
  { title: "text", description: "text" },
  { name: "idx_text_search", weights: { title: 10, description: 1 } }
);
print("Created text index on title and description");

// Index for querying by tags
db.grants.createIndex(
  { tags: 1 },
  { name: "idx_tags" }
);
print("Created index on tags");

// Index for querying by funding amount
db.grants.createIndex(
  { total_fund_gbp: 1 },
  { name: "idx_total_fund" }
);
print("Created index on total_fund_gbp");

// Index for updated_at (for finding recently updated grants)
db.grants.createIndex(
  { updated_at: -1 },
  { name: "idx_updated_at" }
);
print("Created index on updated_at");

// Print summary
print("\n========================================");
print("MongoDB Setup Complete");
print("========================================");
print("Database: ailsa_grants");
print("Collection: grants");
print("");
print("Indexes created:");
db.grants.getIndexes().forEach(function(idx) {
  print("  - " + idx.name);
});

print("\nTo verify, run:");
print("  db.grants.getIndexes()");
print("  db.grants.countDocuments({})");
