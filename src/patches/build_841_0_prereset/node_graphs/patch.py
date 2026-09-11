from patches.definitions import PatchDefinition, Resource
from patches.helpers.node_graphs import NodeGraphsPatch

RESOURCE = Resource("build_841_0_prereset/node_graphs", "graphs.zip")
DEFINITION = PatchDefinition(
    NodeGraphsPatch("841_0_prereset.node_graphs", RESOURCE),
    resources=(RESOURCE,),
)
