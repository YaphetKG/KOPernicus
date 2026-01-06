import React, { useState, useEffect, useRef } from 'react';
import ReactMarkdown from 'react-markdown';
import { Send, Loader2, Network, ChevronDown, ChevronRight, Activity, Database, Zap, Brain, CheckCircle2 } from 'lucide-react';
import { streamAgent } from '../api';
import { GraphVisualizer } from './GraphVisualizer';

interface AgentStep {
    id: string;
    type: 'plan' | 'execution' | 'analysis' | 'decision' | 'synthesis';
    label: string;
    detail?: string;
    status: 'pending' | 'active' | 'completed';
    timestamp: number;
}

interface Message {
    role: 'user' | 'assistant';
    content: string;
    subgraph?: any;
    steps?: AgentStep[];
    isStreaming?: boolean;
}

const AgentProgress: React.FC<{ steps: AgentStep[], isStreaming?: boolean }> = ({ steps, isStreaming }) => {
    const [isOpen, setIsOpen] = useState(true);

    // Auto-expand if streaming
    useEffect(() => {
        if (isStreaming) setIsOpen(true);
    }, [isStreaming, steps.length]);

    if (!steps || steps.length === 0) return null;

    const activeStep = steps.find(s => s.status === 'active') || steps[steps.length - 1];

    return (
        <div className="mb-4 rounded-xl bg-slate-900/40 border border-white/10 overflow-hidden text-sm">
            <button
                onClick={() => setIsOpen(!isOpen)}
                className="w-full flex items-center justify-between p-3 bg-white/5 hover:bg-white/10 transition-colors"
            >
                <div className="flex items-center gap-2">
                    {isStreaming ? (
                        <Activity className="text-blue-400 animate-pulse h-4 w-4" />
                    ) : (
                        <CheckCircle2 className="text-emerald-400 h-4 w-4" />
                    )}
                    <span className="font-medium text-slate-300">
                        {isStreaming ? "Agent Working..." : "Process Completed"}
                    </span>
                    {activeStep && isStreaming && (
                        <span className="text-xs text-slate-500 ml-2 hidden sm:inline-block">
                            • {activeStep.label}
                        </span>
                    )}
                </div>
                {isOpen ? <ChevronDown size={16} className="text-slate-400" /> : <ChevronRight size={16} className="text-slate-400" />}
            </button>

            {isOpen && (
                <div className="p-2 space-y-1 max-h-60 overflow-y-auto custom-scrollbar">
                    {steps.map((step) => (
                        <div key={step.id} className="flex gap-3 p-2 rounded hover:bg-white/5 transition-colors group">
                            <div className="pt-0.5">
                                {step.type === 'plan' && <Brain size={14} className="text-purple-400" />}
                                {step.type === 'execution' && <Zap size={14} className="text-amber-400" />}
                                {step.type === 'analysis' && <Database size={14} className="text-cyan-400" />}
                                {step.type === 'decision' && <Activity size={14} className="text-emerald-400" />}
                                {step.type === 'synthesis' && <Network size={14} className="text-pink-400" />}
                            </div>
                            <div className="flex-1 min-w-0">
                                <div className="flex justify-between items-start">
                                    <span className="text-slate-300 font-medium truncate">
                                        {step.label}
                                    </span>
                                    {step.status === 'active' && (
                                        <span className="flex h-2 w-2 relative">
                                            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-blue-400 opacity-75"></span>
                                            <span className="relative inline-flex rounded-full h-2 w-2 bg-blue-500"></span>
                                        </span>
                                    )}
                                </div>
                                {step.detail && (
                                    <p className="text-xs text-slate-500 mt-0.5 break-words font-mono opacity-80 group-hover:opacity-100">
                                        {step.detail}
                                    </p>
                                )}
                            </div>
                        </div>
                    ))}
                    {isStreaming && (
                        <div className="p-2 flex gap-3 animate-pulse opacity-50">
                            <div className="h-4 w-4 rounded-full bg-slate-700" />
                            <div className="h-4 rounded bg-slate-700 flex-1" />
                        </div>
                    )}
                </div>
            )}
        </div>
    );
};

export const ChatInterface: React.FC = () => {
    const [input, setInput] = useState('');
    const [messages, setMessages] = useState<Message[]>([]);
    const [isLoading, setIsLoading] = useState(false);
    const messagesEndRef = useRef<HTMLDivElement>(null);

    const scrollToBottom = () => {
        messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
    };

    useEffect(scrollToBottom, [messages]);

    const addStep = (msgIndex: number, step: AgentStep) => {
        setMessages(prev => {
            const newMsgs = [...prev];
            if (!newMsgs[msgIndex]) return prev;

            const existingSteps = newMsgs[msgIndex].steps || [];
            // Mark previous active steps as completed
            const updatedSteps = existingSteps.map(s =>
                s.status === 'active' ? { ...s, status: 'completed' as const } : s
            );

            newMsgs[msgIndex] = {
                ...newMsgs[msgIndex],
                steps: [...updatedSteps, step]
            };
            return newMsgs;
        });
    };

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!input.trim() || isLoading) return;

        const userMsg = input;
        setInput('');

        // Add user message
        setMessages(prev => [...prev, { role: 'user', content: userMsg }]);

        // Add placeholder assistant message
        setIsLoading(true);
        setMessages(prev => [...prev, {
            role: 'assistant',
            content: '',
            steps: [],
            isStreaming: true
        }]);

        const msgIndex = messages.length + 1; // Index of the new assistant message

        try {
            await streamAgent(userMsg, (chunk) => {
                const timestamp = Date.now();

                // --- Planner ---
                if (chunk.planner) {
                    addStep(msgIndex, {
                        id: `plan-${timestamp}`,
                        type: 'plan',
                        label: 'Formulated Exploration Strategy',
                        detail: chunk.planner.exploration_strategy,
                        status: 'active',
                        timestamp
                    });
                }

                // --- Exploration Planner (Next Step) ---
                if (chunk.exploration_planner) {
                    const rationale = chunk.exploration_planner.planning_rationale || "";
                    const nextAction = chunk.exploration_planner.plan ? chunk.exploration_planner.plan[0] : "Unknown";
                    addStep(msgIndex, {
                        id: `expl-plan-${timestamp}`,
                        type: 'plan',
                        label: 'Planning Next Step',
                        detail: `Action: ${nextAction}\nRationale: ${rationale}`,
                        status: 'completed',
                        timestamp
                    });
                }

                // --- Executor ---
                if (chunk.executor) {
                    const evidenceItem = chunk.executor.evidence ? chunk.executor.evidence[0] : null;
                    if (evidenceItem) {
                        addStep(msgIndex, {
                            id: `exec-${timestamp}`,
                            type: 'execution',
                            label: `Executed Tool: ${evidenceItem.tool || evidenceItem.step || 'Unknown'}`,
                            detail: evidenceItem.status === 'error'
                                ? `Error: ${evidenceItem.data}`
                                : `Result: ${JSON.stringify(evidenceItem.data).substring(0, 300)}...`,
                            status: 'completed',
                            timestamp
                        });
                    } else {
                        const step = chunk.executor.past_steps ? chunk.executor.past_steps[chunk.executor.past_steps.length - 1] : null;
                        if (step) {
                            addStep(msgIndex, {
                                id: `exec-${timestamp}`,
                                type: 'execution',
                                label: `Executed Tool: ${step[0] || 'Unknown'}`,
                                detail: (step[1] || '').substring(0, 300) + '...',
                                status: 'completed',
                                timestamp
                            });
                        }
                    }
                }

                // --- Schema Analyzer ---
                if (chunk.schema_analyzer && chunk.schema_analyzer.schema_patterns?.length > 0) {
                    addStep(msgIndex, {
                        id: `schema-${timestamp}`,
                        type: 'analysis',
                        label: 'Schema Analysis',
                        detail: `Found ${chunk.schema_analyzer.schema_patterns.length} patterns`,
                        status: 'completed',
                        timestamp
                    });
                }

                // --- Decision Maker ---
                if (chunk.decision_maker) {
                    const reasoning = chunk.decision_maker.decision_reasoning || "";
                    const decision = chunk.decision_maker.should_explore_more ? "Explore More" : "Synthesize Answer";
                    addStep(msgIndex, {
                        id: `decision-${timestamp}`,
                        type: 'decision',
                        label: `Decision: ${decision}`,
                        detail: reasoning,
                        status: 'completed',
                        timestamp
                    });
                }

                // --- Loop Detector ---
                if (chunk.loop_detector) {
                    const data = JSON.parse(chunk.loop_detector.loop_detection || '{}');
                    if (data.is_looping) {
                        addStep(msgIndex, {
                            id: `loop-${timestamp}`,
                            type: 'analysis',
                            label: '⚠️ Loop Detected',
                            detail: data.repeated_pattern,
                            status: 'completed',
                            timestamp
                        });
                    }
                }

                // --- Synthesis Planner ---
                if (chunk.synthesis_planner) {
                    addStep(msgIndex, {
                        id: `synth-plan-${timestamp}`,
                        type: 'synthesis',
                        label: 'Planning Final Answer',
                        status: 'active',
                        timestamp
                    });
                }

                // --- Final Answer ---
                if (chunk.answer_generator) {
                    const output = chunk.answer_generator;
                    setMessages(prev => {
                        const newMsgs = [...prev];
                        if (newMsgs[msgIndex]) {
                            newMsgs[msgIndex] = {
                                ...newMsgs[msgIndex],
                                content: output.response,
                                subgraph: output.critical_subgraph,
                                isStreaming: false,
                                steps: (newMsgs[msgIndex].steps || []).map(s => ({ ...s, status: 'completed' }))
                            };
                        }
                        return newMsgs;
                    });
                }
            });

        } catch (error) {
            setMessages(prev => {
                const newMsgs = [...prev];
                if (newMsgs[msgIndex]) {
                    newMsgs[msgIndex] = {
                        ...newMsgs[msgIndex],
                        content: "Error: Failed to connect to agent.",
                        isStreaming: false
                    };
                }
                return newMsgs;
            });
        } finally {
            setIsLoading(false);
            setMessages(prev => {
                const newMsgs = [...prev];
                if (newMsgs[msgIndex]) {
                    newMsgs[msgIndex] = { ...newMsgs[msgIndex], isStreaming: false };
                }
                return newMsgs;
            });
        }
    };

    return (
        <div className="flex flex-col h-screen bg-slate-950 text-slate-100 font-sans selection:bg-blue-500/30">
            {/* Background Gradient Mesh */}
            <div className="fixed inset-0 z-0 pointer-events-none">
                <div className="absolute top-[-10%] left-[-10%] w-[50%] h-[50%] rounded-full bg-blue-900/20 blur-[100px]" />
                <div className="absolute bottom-[-10%] right-[-10%] w-[50%] h-[50%] rounded-full bg-indigo-900/20 blur-[100px]" />
            </div>

            <header className="relative z-10 bg-slate-900/50 backdrop-blur-md border-b border-white/5 p-4 flex items-center gap-3 shadow-lg">
                <div className="p-2 bg-gradient-to-tr from-blue-600 to-indigo-600 rounded-lg shadow-blue-500/20 shadow-lg">
                    <Network className="text-white h-6 w-6" />
                </div>
                <div>
                    <h1 className="text-xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-blue-100 to-indigo-100">
                        KOPernicus
                    </h1>
                    <p className="text-xs text-slate-400 font-medium">Biomedical Knowledge Explorer</p>
                </div>
            </header>

            <div className="relative z-10 flex-1 overflow-y-auto p-4 space-y-6 scroll-smooth">
                {messages.map((msg, idx) => (
                    <div key={idx} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'} animate-in fade-in slide-in-from-bottom-2 duration-300`}>
                        <div
                            className={`max-w-4xl p-5 rounded-2xl shadow-xl backdrop-blur-sm border ${msg.role === 'user'
                                ? 'bg-gradient-to-br from-blue-600 to-indigo-600 border-transparent text-white rounded-tr-none'
                                : 'bg-slate-800/60 border-white/10 text-slate-200 rounded-tl-none w-full'
                                }`}
                        >
                            {/* Render Steps for Assistant */}
                            {msg.role === 'assistant' && msg.steps && msg.steps.length > 0 && (
                                <AgentProgress steps={msg.steps} isStreaming={msg.isStreaming} />
                            )}

                            {msg.content && (
                                <div
                                    className={`prose prose-invert max-w-none ${msg.role === 'user' ? 'prose-p:text-white prose-a:text-blue-100' : 'prose-headings:text-blue-200 prose-a:text-blue-400'}`}
                                >
                                    <ReactMarkdown>
                                        {msg.content}
                                    </ReactMarkdown>
                                </div>
                            )}

                            {/* Loading state if no content yet */}
                            {!msg.content && msg.isStreaming && (
                                <div className="flex items-center gap-2 text-slate-400 text-sm animate-pulse">
                                    <Loader2 className="animate-spin h-4 w-4" />
                                    <span>Thinking...</span>
                                </div>
                            )}

                            {msg.subgraph && msg.subgraph.nodes && msg.subgraph.nodes.length > 0 && (
                                <div className="mt-6 border-t border-white/10 pt-4">
                                    <h3 className="text-xs font-bold text-slate-400 uppercase tracking-wider mb-3 flex items-center gap-2">
                                        <Network size={14} className="text-blue-400" />
                                        Critical Knowledge Graph
                                    </h3>
                                    <div className="h-80 md:h-[500px] w-full bg-slate-900/50 rounded-xl overflow-hidden border border-white/10 relative shadow-inner">
                                        <GraphVisualizer data={msg.subgraph} />
                                    </div>
                                </div>
                            )}
                        </div>
                    </div>
                ))}

                <div ref={messagesEndRef} />
            </div>

            <div className="relative z-10 p-4 bg-gradient-to-t from-slate-950 via-slate-950 to-transparent">
                <form onSubmit={handleSubmit} className="max-w-5xl mx-auto relative">
                    <input
                        type="text"
                        value={input}
                        onChange={(e) => setInput(e.target.value)}
                        placeholder="Ask a question (e.g., 'What treats Diabetes?')..."
                        className="w-full bg-slate-800/80 backdrop-blur-md border border-white/10 rounded-xl pl-6 pr-14 py-4 focus:outline-none focus:ring-2 focus:ring-blue-500/50 focus:border-blue-500/50 shadow-2xl transition-all text-slate-200 placeholder-slate-500"
                    />
                    <button
                        type="submit"
                        disabled={isLoading}
                        className="absolute right-2 top-2 bottom-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 disabled:hover:bg-blue-600 text-white p-2.5 rounded-lg transition-all shadow-lg hover:shadow-blue-500/25 active:scale-95"
                    >
                        <Send size={20} />
                    </button>
                </form>
            </div >
        </div >
    );
};
