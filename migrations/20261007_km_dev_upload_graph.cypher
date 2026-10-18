// Explicit management migration: approved KM DEV Neo4j only.
CREATE CONSTRAINT km_dev_entity_id_v1 IF NOT EXISTS FOR (e:KmDevKnowledgeEntity) REQUIRE e.id IS UNIQUE;
CREATE CONSTRAINT km_dev_relation_id_v1 IF NOT EXISTS FOR (r:KmDevKnowledgeRelation) REQUIRE r.id IS UNIQUE;
