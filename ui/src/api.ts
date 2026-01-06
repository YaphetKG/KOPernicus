import axios from "axios";

const API_URL = "http://localhost:8822/kopernicus";

export const invokeAgent = async (input: string) => {
  try {
    const response = await axios.post(`${API_URL}/invoke`, {
      input: { input },
    });
    return response.data;
  } catch (error) {
    console.error("Error invoking agent:", error);
    throw error;
  }
};

export const streamAgent = async (input: string, onChunk: (chunk: any) => void) => {
  const response = await fetch(`${API_URL}/stream`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ input: { input } }),
  });

  if (!response.body) return;

  const reader = response.body.getReader();
  const decoder = new TextDecoder();

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    const text = decoder.decode(value);
    // LangServe streams events like "event: data\ndata: {...}\n\n"
    // Simple parsing for now - in production use @langchain/core/tracers/log_stream or similar
    const lines = text.split('\n');
    for (const line of lines) {
      if (line.startsWith('data: ')) {
        try {
          const data = JSON.parse(line.slice(6));
          onChunk(data);
        } catch (e) {
          console.error("Error parsing stream chunk", e);
        }
      }
    }
  }
};
