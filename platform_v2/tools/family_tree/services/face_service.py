import json
import logging
import numpy as np

from database import get_db_cursor

logger = logging.getLogger(__name__)

_face_app = None


def _get_face_app():
    global _face_app
    if _face_app is not None:
        return _face_app
    try:
        from insightface.app import FaceAnalysis

        app = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
        app.prepare(ctx_id=0, det_size=(640, 640))
        _face_app = app
        return _face_app
    except ImportError:
        logger.warning("InsightFace not available — face detection disabled")
        return None
    except Exception as e:
        logger.error("Failed to initialize InsightFace: %s", e)
        return None


def detect_faces(image_path):
    """Detect faces in an image and return list of face dicts."""
    app = _get_face_app()
    if app is None:
        return []
    try:
        import cv2

        img = cv2.imread(image_path)
        if img is None:
            logger.warning("Could not load image: %s", image_path)
            return []
        faces = app.get(img)
        results = []
        for face in faces:
            gender = None
            if hasattr(face, "gender"):
                gender = "male" if face.gender == 1 else "female"
            age = None
            if hasattr(face, "age") and face.age is not None:
                age = int(face.age)
            results.append(
                {
                    "embedding": face.embedding,
                    "bbox": face.bbox.tolist(),
                    "det_score": float(face.det_score),
                    "age": age,
                    "gender": gender,
                }
            )
        return results
    except ImportError:
        logger.warning("cv2 not available — face detection disabled")
        return []
    except Exception as e:
        logger.error("Error detecting faces in %s: %s", image_path, e)
        return []


def save_face_embeddings(user_id, document_id, faces):
    """Insert detected faces into family_face_embeddings."""
    if not faces:
        return
    try:
        with get_db_cursor(commit=True) as (conn, cur):
            for face in faces:
                cur.execute(
                    """
                    INSERT INTO family_face_embeddings
                        (user_id, document_id, embedding, bounding_box, confidence_score)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (
                        user_id,
                        document_id,
                        face["embedding"].tobytes(),
                        json.dumps(face["bbox"]),
                        face["det_score"],
                    ),
                )
    except Exception as e:
        logger.error("Error saving face embeddings: %s", e)


def cluster_faces(user_id):
    """Cluster all face embeddings for a user using DBSCAN. Returns cluster count."""
    try:
        from sklearn.cluster import DBSCAN
    except ImportError:
        logger.warning("sklearn not available — face clustering disabled")
        return 0

    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                "SELECT id, embedding FROM family_face_embeddings WHERE user_id = %s",
                (user_id,),
            )
            rows = cur.fetchall()

        if not rows:
            return 0

        ids = []
        embeddings = []
        for row in rows:
            arr = np.frombuffer(row["embedding"], dtype=np.float32)
            if arr.shape != (512,):
                logger.warning("Skipping face %s — unexpected embedding shape %s", row["id"], arr.shape)
                continue
            ids.append(row["id"])
            embeddings.append(arr)

        if not embeddings:
            return 0

        matrix = np.stack(embeddings)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1, norms)
        matrix = matrix / norms

        labels = DBSCAN(eps=0.5, min_samples=2, metric="cosine").fit(matrix).labels_

        with get_db_cursor(commit=True) as (conn, cur):
            for face_id, label in zip(ids, labels):
                cluster_id = None if label == -1 else int(label)
                cur.execute(
                    "UPDATE family_face_embeddings SET cluster_id = %s WHERE id = %s",
                    (cluster_id, face_id),
                )

        n_clusters = len(set(labels) - {-1})
        return n_clusters

    except Exception as e:
        logger.error("Error clustering faces for user %s: %s", user_id, e)
        return 0


def get_face_clusters(user_id):
    """Return all face embeddings for a user joined with document info."""
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT
                    ffe.id,
                    ffe.document_id,
                    ffe.person_id,
                    ffe.cluster_id,
                    ffe.bounding_box,
                    ffe.confidence_score,
                    ffe.estimated_era,
                    fd.filename,
                    fd.file_path
                FROM family_face_embeddings ffe
                JOIN family_documents fd ON fd.id = ffe.document_id
                WHERE ffe.user_id = %s
                ORDER BY ffe.cluster_id NULLS LAST, ffe.id
                """,
                (user_id,),
            )
            rows = cur.fetchall()
            return [dict(row) for row in rows]
    except Exception as e:
        logger.error("Error fetching face clusters for user %s: %s", user_id, e)
        return []


def label_face(face_id, person_id):
    """Assign a person_id to a face embedding record."""
    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                "UPDATE family_face_embeddings SET person_id = %s WHERE id = %s",
                (person_id, face_id),
            )
    except Exception as e:
        logger.error("Error labeling face %s: %s", face_id, e)
