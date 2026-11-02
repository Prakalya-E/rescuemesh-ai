import geopandas as gpd
import networkx as nx
from shapely.geometry import LineString

from backend.app.services import geo


def write_roads(path, rows):
    roads = gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")
    roads.to_file(path, driver="GeoJSON")
    return str(path)


def test_local_graph_connectivity_and_two_way_assumption(tmp_path):
    path = write_roads(
        tmp_path / "roads.geojson",
        [
            {"fclass": "primary", "maxspeed": 0, "oneway": "yes",
             "geometry": LineString([(77.0, 28.0), (77.01, 28.0)])},
            {"fclass": "secondary", "maxspeed": None, "oneway": "yes",
             "geometry": LineString([(77.01, 28.0), (77.01, 28.01)])},
        ],
    )
    geo._graph.cache_clear()
    graph, nodes = geo._graph(path, 28.0, 77.0)
    start = (28.0, 77.0)
    finish = (28.01, 77.01)

    assert isinstance(graph, nx.Graph)
    assert len(nodes) == 3
    assert nx.has_path(graph, start, finish)
    assert nx.has_path(graph, finish, start)  # Current routing intentionally ignores oneway.
    assert nx.shortest_path_length(graph, start, finish, weight="w") > 0
    assert len(list(nx.connected_components(graph))) == 1


def test_graph_handles_missing_road_class_and_speed(tmp_path):
    path = write_roads(
        tmp_path / "roads_without_speed.geojson",
        [{"geometry": LineString([(77.0, 28.0), (77.01, 28.0)])}],
    )
    geo._graph.cache_clear()
    graph, _ = geo._graph(path, 28.0, 77.0)

    assert graph.number_of_edges() == 1
    edge = next(iter(graph.edges(data=True)))[2]
    assert edge["km"] > 0
    assert edge["w"] > 0
