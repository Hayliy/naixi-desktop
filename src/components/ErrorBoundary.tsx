import React from "react";

interface ErrorBoundaryProps {
  children: React.ReactNode;
  name?: string;
}

interface ErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
  errorInfo: React.ErrorInfo | null;
}

export default class ErrorBoundary extends React.Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false, error: null, errorInfo: null };
  }

  static getDerivedStateFromError(error: Error) {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    console.error(`[ErrorBoundary:${this.props.name || "未知页面"}]`, error, errorInfo);
    this.setState({ errorInfo });
  }

  render() {
    if (this.state.hasError) {
      const label = this.props.name || "页面";
      return (
        <div className="flex flex-col items-center justify-center h-full p-8 text-center">
          <div className="w-12 h-12 rounded-full bg-red-100 flex items-center justify-center mb-4">
            <svg className="w-6 h-6 text-red-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          </div>
          <h3 className="text-sm font-semibold text-gray-700 mb-1">{label} 出错了</h3>
          <p className="text-xs text-gray-400 mb-3 max-w-md">
            {this.state.error?.message || "未知错误"}
          </p>
          <button
            onClick={() => this.setState({ hasError: false, error: null, errorInfo: null })}
            className="px-4 py-2 rounded-lg text-xs bg-sakura-100 text-sakura-600 hover:bg-sakura-200 transition-colors"
          >
            重试
          </button>
          <details className="mt-4 max-w-md text-left">
            <summary className="text-[10px] text-gray-400 cursor-pointer hover:text-gray-600">错误详情</summary>
            <pre className="mt-2 text-[10px] text-red-500 bg-red-50 p-3 rounded-lg overflow-auto max-h-[200px] whitespace-pre-wrap">
              {this.state.error?.stack || "无堆栈信息"}
            </pre>
          </details>
        </div>
      );
    }
    return this.props.children;
  }
}
