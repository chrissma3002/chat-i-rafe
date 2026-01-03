import { useState, useEffect } from 'react';
import ModelGrid from './components/ModelGrid';
import ChatInterface from './components/ChatInterface';
import { models } from './models';

function App() {
  const [selectedModelId, setSelectedModelId] = useState<string | null>(null);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const modelParam = params.get('model');
    if (modelParam && models.find((m) => m.id === modelParam)) {
      setSelectedModelId(modelParam);
    } else {
      setSelectedModelId(null);
    }
  }, []);

  const handleSelectModel = (modelId: string) => {
    setSelectedModelId(modelId);
    const params = new URLSearchParams();
    params.set('model', modelId);
    window.history.pushState({}, '', `?${params.toString()}`);
  };

  const handleBack = () => {
    setSelectedModelId(null);
    window.history.pushState({}, '', window.location.pathname);
  };

  const selectedModel = models.find((m) => m.id === selectedModelId);

  if (selectedModel) {
    return <ChatInterface model={selectedModel} onBack={handleBack} />;
  }

  return <ModelGrid models={models} onSelectModel={handleSelectModel} />;
}

export default App;
