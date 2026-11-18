import { Component, type ErrorInfo, type ReactNode } from 'react';
import { Button, Card } from '../asaas-ui';

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('Route ErrorBoundary caught:', error, info);
  }

  render() {
    if (this.state.error) {
      return (
        <main className="container" style={{ paddingBlock: 32 }}>
          <Card title="حدث خطأ غير متوقع" icon="alert">
            <p className="muted">{this.state.error.message}</p>
            <div className="cluster" style={{ marginTop: 12 }}>
              <Button variant="primary" onClick={() => window.location.reload()}>
                إعادة تحميل الصفحة
              </Button>
            </div>
          </Card>
        </main>
      );
    }
    return this.props.children;
  }
}
