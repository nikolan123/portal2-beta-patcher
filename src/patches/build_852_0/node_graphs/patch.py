from patches.definitions import PatchDefinition, Resource
from patches.helpers.node_graphs import NodeGraphsPatch

RESOURCE = Resource("build_852_0/node_graphs", "graphs.zip")
DEFINITION = PatchDefinition(
    NodeGraphsPatch("852_0.node_graphs", RESOURCE),
    after=frozenset({"852_0.hammer", "852_0.continuous_campaign"}),
    resources=(RESOURCE,),
)
