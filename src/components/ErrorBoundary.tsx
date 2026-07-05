import React from "react";

interface ErrorBoundaryProps {
  children: React.ReactNode;
  name?: string;
}

interface ErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
  errorInfo: React.ErrorInfo | null;
  errorCount: number;
}

export default class ErrorBoundary extends React.Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false, error: null, errorInfo: null, errorCount: 0 };
  }

  static getDerivedStateFromError(error: Error) {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    console.error(`[ErrorBoundary:${this.props.name || "未知页面"}]`, error, errorInfo);
    this.setState(prev => ({ errorInfo, errorCount: prev.errorCount + 1 }));
  }

  handleRetry = () => {
    const { errorCount } = this.state;
    // 连续崩溃 3 次以上给特殊提示
    if (errorCount >= 3) {
      this.setState({
        hasError: false, error: null, errorInfo: null,
        errorCount: 0,
      });
    } else {
      this.setState({ hasError: false, error: null, errorInfo: null });
    }
  };

  copyError = () => {
    const text = `[${this.props.name || "未知页面"}]\n${this.state.error?.message || "未知错误"}\n\n${this.state.error?.stack || "无堆栈"}`;
    navigator.clipboard.writeText(text).catch(() => {});
  };

  render() {
    if (this.state.hasError) {
      const label = this.props.name || "页面";
      const errMsg = this.state.error?.message || "未知错误";
      return (
        <div className="flex flex-col items-center justify-center h-full p-8 text-center">
          <div className="w-14 h-14 rounded-full bg-red-100 flex items-center justify-center mb-4">
            <span className="text-2xl">!</span>
          </div>
          <h3 className="text-sm font-semibold text-gray-700 mb-1">{label} 出错了</h3>
          <p className="text-xs text-gray-400 mb-4 max-w-md leading-relaxed">
            {errMsg}
            {this.state.errorCount >= 2 && (
              <span className="block mt-1 text-amber-500">已连续崩溃 {this.state.errorCount} 次</span>
            )}
          </p>
          <div className="flex items-center gap-2">
            <button onClick={this.handleRetry}
              className="px-4 py-2 rounded-lg text-xs bg-sakura-100 text-sakura-600 hover:bg-sakura-200 transition-colors">
              重试
            </button>
            <button onClick={this.copyError}
              className="px-4 py-2 rounded-lg text-xs bg-gray-100 text-gray-500 hover:bg-gray-200 transition-colors">
              复制错误
            </button>
          </div>
          <details className="mt-4 max-w-lg text-left w-full" open>
            <summary className="text-[10px] text-gray-400 cursor-pointer hover:text-gray-600">错误详情（堆栈）</summary>
            <pre className="mt-2 text-[10px] text-red-500 bg-red-50 p-3 rounded-lg overflow-auto max-h-[200px] whitespace-pre-wrap text-left leading-relaxed">
              {this.state.error?.stack || "无堆栈信息"}
            </pre>
            {this.state.errorInfo?.componentStack && (
              <pre className="mt-1 text-[10px] text-amber-600 bg-amber-50 p-3 rounded-lg overflow-auto max-h-[120px] whitespace-pre-wrap text-left leading-relaxed">
                {this.state.errorInfo.componentStack}
              </pre>
            )}
          </details>
        </div>
      );
    }
    return this.props.children;
  }
}
