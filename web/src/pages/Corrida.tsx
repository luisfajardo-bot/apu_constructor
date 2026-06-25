import { useParams } from "react-router-dom";

export default function Corrida() {
  const { id } = useParams<{ id: string }>();
  return <h2 style={{ padding: "1rem" }}>Corrida #{id}</h2>;
}
