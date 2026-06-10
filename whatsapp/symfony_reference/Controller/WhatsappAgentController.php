<?php

declare(strict_types=1);

namespace App\Controller;

use App\Entity\WhatsappOutbox;
use App\Repository\WhatsappOutboxRepository;
use Doctrine\ORM\EntityManagerInterface;
use Symfony\Bundle\FrameworkBundle\Controller\AbstractController;
use Symfony\Component\HttpFoundation\JsonResponse;
use Symfony\Component\HttpFoundation\Request;
use Symfony\Component\HttpFoundation\Response;
use Symfony\Component\Routing\Attribute\Route;

#[Route('/api/whatsapp')]
final class WhatsappAgentController extends AbstractController
{
    public function __construct(
        private readonly WhatsappOutboxRepository $outboxRepository,
        private readonly EntityManagerInterface $em,
    ) {
    }

    /**
     * Агент забирает пачку сообщений на отправку.
     *
     * GET /api/whatsapp/outbox?agent_id=office-main&limit=5
     * Authorization: Bearer {CRM_AGENT_TOKEN}
     */
    #[Route('/outbox', name: 'whatsapp_outbox_fetch', methods: ['GET'])]
    public function fetchOutbox(Request $request): JsonResponse
    {
        $agentId = (string) $request->query->get('agent_id', '');
        $limit = min(20, max(1, (int) $request->query->get('limit', 5)));

        if ($agentId === '') {
            return $this->json(['error' => 'agent_id обязателен'], Response::HTTP_BAD_REQUEST);
        }

        $this->denyAccessUnlessGranted('ROLE_WHATSAPP_AGENT');
        $tokenAgentId = $this->getParameter('whatsapp.agent_id');
        if ($tokenAgentId !== null && $agentId !== $tokenAgentId) {
            return $this->json(['error' => 'agent_id не совпадает с токеном'], Response::HTTP_FORBIDDEN);
        }

        $messages = $this->outboxRepository->claimBatch($agentId, $limit);

        return $this->json([
            'messages' => array_map(static fn (WhatsappOutbox $m) => [
                'id' => $m->getId(),
                'phone' => $m->getPhone(),
                'text' => $m->getBody(),
                'attempts' => $m->getAttempts(),
                'order_id' => $m->getOrderId(),
            ], $messages),
        ]);
    }

    /**
     * Подтверждение отправки или ошибки.
     *
     * POST /api/whatsapp/outbox/{id}/ack
     * {"status":"sent","message_id":"...","sent_at":"2026-06-10T10:00:00+00:00"}
     * {"status":"failed","error":"WhatsApp не авторизован"}
     */
    #[Route('/outbox/{id}/ack', name: 'whatsapp_outbox_ack', methods: ['POST'], requirements: ['id' => '\d+'])]
    public function ack(int $id, Request $request): JsonResponse
    {
        $this->denyAccessUnlessGranted('ROLE_WHATSAPP_AGENT');

        $payload = json_decode($request->getContent(), true);
        if (!is_array($payload)) {
            return $this->json(['error' => 'Некорректный JSON'], Response::HTTP_BAD_REQUEST);
        }

        $status = $payload['status'] ?? '';
        if (!in_array($status, ['sent', 'failed'], true)) {
            return $this->json(['error' => 'status должен быть sent или failed'], Response::HTTP_BAD_REQUEST);
        }

        /** @var WhatsappOutbox|null $message */
        $message = $this->outboxRepository->find($id);
        if ($message === null) {
            return $this->json(['error' => 'Сообщение не найдено'], Response::HTTP_NOT_FOUND);
        }

        if ($message->getStatus() === WhatsappOutbox::STATUS_SENT) {
            return $this->json(['ok' => true, 'idempotent' => true]);
        }

        $message->setLockedAt(null);
        $message->setLockedBy(null);
        $message->touch();

        if ($status === 'sent') {
            $message->setStatus(WhatsappOutbox::STATUS_SENT);
            $message->setExternalMessageId(isset($payload['message_id']) ? (string) $payload['message_id'] : null);
            $message->setErrorMessage(null);

            $sentAtRaw = $payload['sent_at'] ?? null;
            if (is_string($sentAtRaw) && $sentAtRaw !== '') {
                $message->setSentAt(new \DateTimeImmutable($sentAtRaw));
            } else {
                $message->setSentAt(new \DateTimeImmutable());
            }
        } else {
            $message->setErrorMessage(isset($payload['error']) ? (string) $payload['error'] : 'Ошибка отправки');
            if ($message->getAttempts() >= $message->getMaxAttempts()) {
                $message->setStatus(WhatsappOutbox::STATUS_FAILED);
            } else {
                $message->setStatus(WhatsappOutbox::STATUS_PENDING);
            }
        }

        $this->em->flush();

        return $this->json(['ok' => true]);
    }

    /**
     * Пульс офисного агента (для мониторинга в CRM).
     *
     * POST /api/whatsapp/agent/heartbeat
     * {"agent_id":"office-main","logged_in":true,"version":"1.0"}
     */
    #[Route('/agent/heartbeat', name: 'whatsapp_agent_heartbeat', methods: ['POST'])]
    public function heartbeat(Request $request): JsonResponse
    {
        $this->denyAccessUnlessGranted('ROLE_WHATSAPP_AGENT');

        $payload = json_decode($request->getContent(), true);
        if (!is_array($payload)) {
            return $this->json(['error' => 'Некорректный JSON'], Response::HTTP_BAD_REQUEST);
        }

        $agentId = (string) ($payload['agent_id'] ?? '');
        if ($agentId === '') {
            return $this->json(['error' => 'agent_id обязателен'], Response::HTTP_BAD_REQUEST);
        }

        $conn = $this->em->getConnection();
        $now = (new \DateTimeImmutable())->format('Y-m-d H:i:s');
        $loggedIn = !empty($payload['logged_in']) ? 1 : 0;
        $version = isset($payload['version']) ? (string) $payload['version'] : null;

        $conn->executeStatement(
            'INSERT INTO whatsapp_agent_heartbeat (agent_id, logged_in, version, last_seen_at, updated_at)
             VALUES (:agentId, :loggedIn, :version, :now, :now)
             ON DUPLICATE KEY UPDATE
                logged_in = VALUES(logged_in),
                version = VALUES(version),
                last_seen_at = VALUES(last_seen_at),
                updated_at = VALUES(updated_at)',
            [
                'agentId' => $agentId,
                'loggedIn' => $loggedIn,
                'version' => $version,
                'now' => $now,
            ]
        );

        return $this->json(['ok' => true]);
    }
}
