from . import db

def remember(content: str, tags: str = "", importance: int = 3):
    content = content.strip()
    if not content:
        raise ValueError("Une mémoire ne peut pas être vide.")
    if len(content) > 10000:
        raise ValueError("Mémoire trop longue (10 000 caractères maximum).")
    if not 1 <= importance <= 5:
        raise ValueError("importance doit être comprise entre 1 et 5.")
    return {"id": db.add_memory(content, tags[:500], importance)}

def recall(query: str = "", limit: int = 20):
    return db.search_memories(query, limit)

def forget(memory_id: int):
    if not db.delete_memory(memory_id):
        raise KeyError("Mémoire introuvable.")
    return {"deleted": memory_id}
