import Markdown from 'react-markdown'
import rehypeHighlight from 'rehype-highlight'

interface MarkdownAnswerProps {
  answer: string
}

export default function MarkdownAnswer({ answer }: MarkdownAnswerProps) {
  return <Markdown rehypePlugins={[rehypeHighlight]}>{answer}</Markdown>
}
