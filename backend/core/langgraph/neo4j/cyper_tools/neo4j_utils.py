from typing import Any, Dict, List

from neo4j import GraphDatabase


class Neo4jConnector:
    def __init__(self, uri: str, user: str, password: str):
        self.driver = GraphDatabase.driver(uri, auth=(user, password))

    def close(self):
        self.driver.close()

    def run_cypher(self, cypher_query: str,
                   parameters: Dict[str, Any] = None) -> List[Dict[str, Any]]:
        """
        Thực thi một truy vấn Cypher và trả về danh sách record (dạng dict).
        """
        if parameters is None:
            parameters = {}
        with self.driver.session() as session:
            result = session.run(cypher_query, parameters)
            return [record.data() for record in result]