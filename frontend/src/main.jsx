import React from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import './styles.css';

// An error while rendering one screen used to leave a blank white page.
// Show a way back instead and keep the details in the browser console.
class ErrorBoundary extends React.Component {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  componentDidCatch(error, info) { console.error('Interface error', error, info?.componentStack); }
  render() {
    if (!this.state.failed) return this.props.children;
    return <div className="welcome-screen"><div className="welcome-loading" role="alert">
      <p>На странице произошла ошибка. Обновите страницу, чтобы продолжить работу.</p>
      <button className="primary" onClick={() => window.location.reload()}>Обновить страницу</button>
    </div></div>;
  }
}

createRoot(document.getElementById('root')).render(<React.StrictMode><ErrorBoundary><App /></ErrorBoundary></React.StrictMode>);
