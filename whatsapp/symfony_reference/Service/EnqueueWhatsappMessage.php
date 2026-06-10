<?php

declare(strict_types=1);

namespace App\Service;

use App\Entity\WhatsappOutbox;
use Doctrine\ORM\EntityManagerInterface;

/**
 * Пример: поставить сообщение в очередь из бизнес-логики CRM.
 *
 * $enqueue->enqueue(
 *     agentId: 'office-main',
 *     phone: '+79001234567',
 *     body: 'Заказ #123 готов к выдаче',
 *     orderId: 123,
 * );
 */
final class EnqueueWhatsappMessage
{
    public function __construct(
        private readonly EntityManagerInterface $em,
        private readonly string $defaultAgentId,
    ) {
    }

    public function enqueue(
        string $phone,
        string $body,
        ?string $agentId = null,
        ?int $orderId = null,
        ?\DateTimeInterface $scheduledAt = null,
    ): WhatsappOutbox {
        $message = (new WhatsappOutbox())
            ->setAgentId($agentId ?? $this->defaultAgentId)
            ->setPhone($phone)
            ->setBody($body)
            ->setOrderId($orderId);

        if ($scheduledAt !== null) {
            $message->setScheduledAt($scheduledAt);
        }

        $this->em->persist($message);
        $this->em->flush();

        return $message;
    }
}
