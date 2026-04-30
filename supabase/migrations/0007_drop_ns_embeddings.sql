-- 0007_drop_ns_embeddings.sql
--
-- Suite du POC cleanup : drop de la table d'embeddings RAG.
-- Les 128 vecteurs étaient des embeddings sur script_docs.content_md.
-- On garde script_docs (la doc IA), mais on enlève le RAG sémantique.

BEGIN;

DROP TABLE IF EXISTS public.ns_embeddings CASCADE;

COMMIT;
