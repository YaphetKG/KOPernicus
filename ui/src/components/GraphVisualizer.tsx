import React, { useRef, useEffect } from 'react';
import ForceGraph2D from 'react-force-graph-2d';

interface GraphVisualizerProps {
    data: {
        nodes: any[];
        edges: any[];
    };
}

export const GraphVisualizer: React.FC<GraphVisualizerProps> = ({ data }) => {
    const containerRef = useRef<HTMLDivElement>(null);
    const fgRef = useRef<any>(null);

    useEffect(() => {
        // Zoom to fit on load
        if (fgRef.current) {
            fgRef.current.zoomToFit(400);
        }
    }, [data]);

    const handleNodeClick = (node: any) => {
        // Construct RoboKOP link
        if (node.id) {
            // Simple heuristic for RoboKOP URL - often expects CURIEs
            const url = `https://robokop.renci.org/browse/${encodeURIComponent(node.id)}`;
            window.open(url, '_blank');
        }
    };

    return (
        <div ref={containerRef} className="w-full h-full">
            <ForceGraph2D
                ref={fgRef}
                graphData={{
                    nodes: data.nodes,
                    links: data.edges.map(e => ({
                        ...e,
                        source: e.source || e.subject,
                        target: e.target || e.object
                    }))
                }}
                width={containerRef.current?.clientWidth}
                height={containerRef.current?.clientHeight}
                nodeLabel="name"
                nodeColor={(node: any) => (node.type === 'ChemicalEntity' || node.id?.startsWith('CHEBI')) ? '#ef4444' : (node.type === 'Disease' || node.id?.startsWith('MONDO')) ? '#3b82f6' : '#10b981'}
                nodeRelSize={6}
                linkColor={() => '#4b5563'}
                linkDirectionalArrowLength={3.5}
                linkDirectionalArrowRelPos={1}
                onNodeClick={handleNodeClick}
                backgroundColor="#111827"
            />
            <div className="absolute top-2 right-2 bg-gray-900/80 p-2 rounded text-xs text-gray-500 pointer-events-none">
                Click node to view in RoboKOP
            </div>
        </div>
    );
};
