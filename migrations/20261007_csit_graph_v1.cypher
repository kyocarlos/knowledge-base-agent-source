// Explicit management migration: approved KM DEV Neo4j only.
CREATE CONSTRAINT csit_entity_id_v1 IF NOT EXISTS FOR (e:CsitKnowledgeEntity) REQUIRE e.id IS UNIQUE;
CREATE CONSTRAINT csit_relation_id_v1 IF NOT EXISTS FOR (r:CsitKnowledgeRelation) REQUIRE r.id IS UNIQUE;
