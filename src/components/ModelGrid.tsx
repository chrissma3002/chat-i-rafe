import { AIModel } from '../types';

interface ModelGridProps {
  models: AIModel[];
  onSelectModel: (modelId: string) => void;
}

export default function ModelGrid({ models, onSelectModel }: ModelGridProps) {
  return (
    <div className="min-h-screen bg-[#131314] text-[#e3e3e3]">
      <div className="max-w-7xl mx-auto px-4 py-12 md:py-16">
        <div className="text-center mb-12">
          <h1 className="text-4xl md:text-5xl font-semibold mb-4 font-robotic">
            AI Nigga
          </h1>
          <p className="text-lg text-[#9da0a5]">
            Choose your AI assistant to start chatting
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {models.map((model) => (
            <div
              key={model.id}
              className="model-card bg-[#28292a] border border-[#363739] rounded-[16px] p-6 transition-all duration-300 hover:bg-[#353638] hover:border-[#6366f1] hover:shadow-lg hover:-translate-y-1 cursor-pointer"
              onClick={() => onSelectModel(model.id)}
            >
              <div className="flex items-start justify-between mb-4">
                <div className="text-4xl">{model.icon}</div>
                <span className="px-3 py-1 text-xs font-medium rounded-full bg-[#6366f1]/20 text-[#6366f1]">
                  {model.category}
                </span>
              </div>

              <h3 className="text-xl font-semibold mb-2">{model.name}</h3>

              <p className="text-[#9da0a5] text-sm mb-4">
                {model.description}
              </p>

              <div className="flex items-center justify-between">
                <span className="text-xs text-[#9da0a5] capitalize">
                  by {model.provider}
                </span>
                <button className="px-4 py-2 bg-[#6366f1] text-white rounded-lg font-medium text-sm hover:bg-[#5558e3] transition-colors">
                  Launch Chat
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
